package com.netpresence

import android.annotation.SuppressLint
import android.bluetooth.BluetoothManager
import android.bluetooth.le.AdvertiseCallback
import android.bluetooth.le.AdvertiseData
import android.bluetooth.le.AdvertiseSettings
import android.bluetooth.le.BluetoothLeAdvertiser
import android.bluetooth.le.BluetoothLeScanner
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.os.Build
import android.os.ParcelUuid
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import com.facebook.react.bridge.Arguments
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import com.facebook.react.modules.core.DeviceEventManagerModule
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.PrivateKey
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import java.util.UUID

/**
 * Native half of the NetPresence phone: hardware-backed ECDSA P-256 key + BLE advertise/scan.
 *
 * NOT built or run in CI (no Android SDK in the dev sandbox) - see mobile/README.md "Verification status".
 *
 * Advertised identity: the ephemeral id is carried as ASCII in manufacturer data (company id 0xFFFF) inside the
 * scan response, and the service UUID in the primary advertisement. Scanners synthesise the name "NP-<eph>" so
 * Android and iOS peers (iOS advertises the same string as its LocalName) look identical to the JS core.
 */
class NetPresenceModule(private val ctx: ReactApplicationContext) : ReactContextBaseJavaModule(ctx) {
  override fun getName() = "NetPresenceNative"

  private val alias = "netpresence.device.key"

  // ---------------------------------------------------------------- keys
  private fun privateKey(): PrivateKey {
    val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
    (ks.getKey(alias, null) as? PrivateKey)?.let { return it }
    fun gen(strongBox: Boolean) {
      val b = KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_SIGN)
        .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
        .setDigests(KeyProperties.DIGEST_SHA256)
        .setUserAuthenticationRequired(false)
      if (strongBox && Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) b.setIsStrongBoxBacked(true)
      KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, "AndroidKeyStore").apply { initialize(b.build()) }.generateKeyPair()
    }
    try { gen(true) } catch (e: Exception) { gen(false) } // StrongBox is absent on most mid-range phones
    return ks.getKey(alias, null) as PrivateKey
  }

  @ReactMethod
  fun publicKey(promise: Promise) {
    try {
      privateKey()
      val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
      // getEncoded() of an EC public key is X.509 SubjectPublicKeyInfo DER, which is what the server expects.
      promise.resolve(Base64.encodeToString(ks.getCertificate(alias).publicKey.encoded, Base64.NO_WRAP))
    } catch (e: Exception) { promise.reject("E_KEY", e) }
  }

  @ReactMethod
  fun sign(message: String, promise: Promise) {
    try {
      val s = Signature.getInstance("SHA256withECDSA").apply { initSign(privateKey()); update(message.toByteArray(Charsets.UTF_8)) }
      promise.resolve(Base64.encodeToString(s.sign(), Base64.NO_WRAP)) // ASN.1 DER
    } catch (e: Exception) { promise.reject("E_SIGN", e) }
  }

  @ReactMethod
  fun deviceModel(promise: Promise) = promise.resolve("${Build.MANUFACTURER} ${Build.MODEL}")

  @ReactMethod
  fun setKeepAwake(on: Boolean) {
    val a = currentActivity ?: return
    a.runOnUiThread {
      if (on) a.window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
      else a.window.clearFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }
  }

  // ---------------------------------------------------------------- radio
  private var scanner: BluetoothLeScanner? = null
  private var advertiser: BluetoothLeAdvertiser? = null
  private var scanCb: ScanCallback? = null
  private var advCb: AdvertiseCallback? = null

  private fun emit(name: String, rssi: Int) {
    val m = Arguments.createMap().apply { putString("name", name); putInt("rssi", rssi) }
    ctx.getJSModule(DeviceEventManagerModule.RCTDeviceEventEmitter::class.java).emit("NPSample", m)
  }

  @SuppressLint("MissingPermission") // permissions are requested from JS before start()
  @ReactMethod
  fun startRadio(advertiseName: String, serviceUuid: String, promise: Promise) {
    try {
      stopInternal()
      val adapter = (ctx.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager).adapter
      if (adapter == null || !adapter.isEnabled) { promise.reject("E_BT_OFF", "Bluetooth is off"); return }
      val uuid = ParcelUuid(UUID.fromString(serviceUuid))
      val eph = advertiseName.removePrefix("NP-")

      advertiser = adapter.bluetoothLeAdvertiser
      advCb = object : AdvertiseCallback() {
        override fun onStartFailure(errorCode: Int) { emit("NP-ERR-ADV-$errorCode", -1) }
      }
      advertiser?.startAdvertising(
        AdvertiseSettings.Builder()
          .setAdvertiseMode(AdvertiseSettings.ADVERTISE_MODE_LOW_LATENCY)
          .setTxPowerLevel(AdvertiseSettings.ADVERTISE_TX_POWER_LOW) // short range on purpose; RSSI gating does the rest
          .setConnectable(false).setTimeout(0).build(),
        AdvertiseData.Builder().setIncludeDeviceName(false).addServiceUuid(uuid).build(),
        AdvertiseData.Builder().setIncludeDeviceName(false).addManufacturerData(0xFFFF, eph.toByteArray(Charsets.US_ASCII)).build(),
        advCb,
      )

      scanner = adapter.bluetoothLeScanner
      scanCb = object : ScanCallback() {
        override fun onScanResult(callbackType: Int, r: ScanResult) {
          val rec = r.scanRecord
          // Android peers: manufacturer data. iOS peers: LocalName "NP-xxxxxxxx".
          val mfr = rec?.getManufacturerSpecificData(0xFFFF)?.toString(Charsets.US_ASCII)
          val name = if (mfr != null && mfr.isNotEmpty()) "NP-$mfr" else rec?.deviceName
          if (name != null && name.startsWith("NP-")) emit(name, r.rssi)
        }
        override fun onScanFailed(errorCode: Int) { emit("NP-ERR-SCAN-$errorCode", -1) }
      }
      scanner?.startScan(
        listOf(ScanFilter.Builder().setServiceUuid(uuid).build()),
        // LOW_LATENCY is essential: BALANCED/LOW_POWER duty-cycle the radio and starve the RSSI sample count.
        ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).setReportDelay(0).build(),
        scanCb,
      )
      promise.resolve(null)
    } catch (e: Exception) { promise.reject("E_RADIO", e) }
  }

  @SuppressLint("MissingPermission")
  private fun stopInternal() {
    try { scanCb?.let { scanner?.stopScan(it) } } catch (_: Exception) {}
    try { advCb?.let { advertiser?.stopAdvertising(it) } } catch (_: Exception) {}
    scanCb = null; advCb = null
  }

  @ReactMethod fun stopRadio(promise: Promise) { stopInternal(); promise.resolve(null) }
  @ReactMethod fun addListener(eventName: String) {}
  @ReactMethod fun removeListeners(count: Int) {}
}
