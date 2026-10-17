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
import android.location.LocationManager
import android.os.Build
import android.os.Handler
import android.os.Looper
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
 * Advertised identity: the ephemeral id is the last 32 bits of the advertised service UUID (see startRadio), identical
 * to what the iOS module advertises. Scanners report peers to JS as "NP-<eph>" in batches every 200 ms.
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
    val a = ctx.currentActivity ?: return
    a.runOnUiThread {
      if (on) a.window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
      else a.window.clearFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }
  }

  // ---------------------------------------------------------------- radio
  // On air: ONE legacy advertisement = flags + a 128-bit service UUID whose last 32 bits are the ephemeral id
  // (6e657470-7265-7365-6e63-6500XXXXXXXX). 21 bytes: fits with room to spare, no scan response, no device name, so a
  // passive or colliding scan still gets the identity. iOS advertises exactly the same thing.
  private val prefix = "6e657470-7265-7365-6e63-6500"
  private val scanBase = ParcelUuid(UUID.fromString(prefix + "00000000"))
  private val scanMask = ParcelUuid(UUID.fromString("ffffffff-ffff-ffff-ffff-ffff00000000"))

  private var scanner: BluetoothLeScanner? = null
  private var advertiser: BluetoothLeAdvertiser? = null
  private var scanCb: ScanCallback? = null
  private var advCb: AdvertiseCallback? = null

  // Samples are batched and sent to JS every FLUSH_MS: ~90 peers x ~10 adverts/s would otherwise be ~900 bridge
  // events per second, enough to stall the UI thread on a mid-range phone.
  private val FLUSH_MS = 200L
  private val main = Handler(Looper.getMainLooper())
  private val buffer = ArrayList<Pair<String, Int>>()
  private val flusher = object : Runnable {
    override fun run() { flush(); main.postDelayed(this, FLUSH_MS) }
  }

  private fun flush() {
    val batch: List<Pair<String, Int>>
    synchronized(buffer) { if (buffer.isEmpty()) return; batch = ArrayList(buffer); buffer.clear() }
    val arr = Arguments.createArray()
    for ((n, r) in batch) arr.pushMap(Arguments.createMap().apply { putString("name", n); putInt("rssi", r) })
    ctx.getJSModule(DeviceEventManagerModule.RCTDeviceEventEmitter::class.java).emit("NPSamples", arr)
  }

  private fun push(name: String, rssi: Int) { synchronized(buffer) { if (buffer.size < 20000) buffer.add(name to rssi) } }

  /** Bluetooth scanning returns nothing on Android 11 and older while Location is switched off (OS rule). */
  private fun locationOffBlocksScan(): Boolean {
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) return false
    val lm = ctx.getSystemService(Context.LOCATION_SERVICE) as? LocationManager ?: return false
    return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) !lm.isLocationEnabled
    else !(lm.isProviderEnabled(LocationManager.GPS_PROVIDER) || lm.isProviderEnabled(LocationManager.NETWORK_PROVIDER))
  }

  @SuppressLint("MissingPermission") // permissions are requested from JS before start()
  @ReactMethod
  fun startRadio(advertiseName: String, advertiseUuid: String, promise: Promise) {
    try {
      stopInternal()
      val uuid = try { UUID.fromString(advertiseUuid) } catch (e: IllegalArgumentException) {
        promise.reject("E_ARG", "Bad advertise UUID"); return }
      val manager = ctx.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager
      val adapter = manager?.adapter
      if (adapter == null) { promise.reject("E_NO_BT", "This phone has no Bluetooth"); return }
      if (!adapter.isEnabled) { promise.reject("E_BT_OFF", "Bluetooth is off. Turn it on and try again."); return }
      if (locationOffBlocksScan()) { promise.reject("E_LOCATION_OFF", "Turn on Location: Android 11 and older need it for Bluetooth scanning."); return }

      // Advertise (some low-end phones cannot advertise at all: they can still scan and report, so warn, don't fail)
      advertiser = if (adapter.isMultipleAdvertisementSupported) adapter.bluetoothLeAdvertiser else null
      if (advertiser == null) push("NP-ERR-ADV-UNSUPPORTED", -1)
      advCb = object : AdvertiseCallback() {
        override fun onStartFailure(errorCode: Int) { push("NP-ERR-ADV-$errorCode", -1) }
      }
      advertiser?.startAdvertising(
        AdvertiseSettings.Builder()
          .setAdvertiseMode(AdvertiseSettings.ADVERTISE_MODE_LOW_LATENCY)        // ~100 ms interval
          // HIGH, not LOW: iOS cannot lower its TX power, so matching it keeps Android<->iPhone links symmetric
          // (the server's self-calibration removes what is left)
          .setTxPowerLevel(AdvertiseSettings.ADVERTISE_TX_POWER_HIGH)
          .setConnectable(false).setTimeout(0).build(),
        AdvertiseData.Builder().setIncludeDeviceName(false).setIncludeTxPowerLevel(false)
          .addServiceUuid(ParcelUuid(uuid)).build(),
        advCb,
      )

      scanner = adapter.bluetoothLeScanner
      if (scanner == null) { stopInternal(); promise.reject("E_NO_SCAN", "Bluetooth scanner unavailable. Toggle Bluetooth and retry."); return }
      scanCb = object : ScanCallback() {
        override fun onScanResult(callbackType: Int, r: ScanResult) {
          val uuids = r.scanRecord?.serviceUuids ?: return
          for (pu in uuids) {
            val u = pu.uuid.toString()                       // lower-case canonical form
            if (u.length == 36 && u.startsWith(prefix)) push("NP-" + u.substring(prefix.length), r.rssi)   // EVERY match: one radio sending two ids is evidence
          }
        }
        override fun onBatchScanResults(results: MutableList<ScanResult>) { for (x in results) onScanResult(0, x) }
        override fun onScanFailed(errorCode: Int) { push("NP-ERR-SCAN-$errorCode", -1) }
      }
      scanner?.startScan(
        listOf(ScanFilter.Builder().setServiceUuid(scanBase, scanMask).build()),   // hardware filter on the prefix
        // LOW_LATENCY is essential: BALANCED/LOW_POWER duty-cycle the radio and starve the RSSI sample count.
        ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
          .setCallbackType(ScanSettings.CALLBACK_TYPE_ALL_MATCHES).setReportDelay(0).build(),
        scanCb,
      )
      main.removeCallbacks(flusher)
      main.postDelayed(flusher, FLUSH_MS)
      promise.resolve(null)
    } catch (e: SecurityException) {
      stopInternal(); promise.reject("E_PERMISSION", "Bluetooth permission missing. Allow 'Nearby devices' for NetPresence.")
    } catch (e: Exception) { stopInternal(); promise.reject("E_RADIO", e) }
  }

  @SuppressLint("MissingPermission")
  private fun stopInternal() {
    try { scanCb?.let { scanner?.stopScan(it) } } catch (_: Exception) {}
    try { advCb?.let { advertiser?.stopAdvertising(it) } } catch (_: Exception) {}
    scanCb = null; advCb = null
    main.removeCallbacks(flusher)
    flush()                                                   // deliver what was heard before stopping
  }

  @ReactMethod fun stopRadio(promise: Promise) { stopInternal(); promise.resolve(null) }
  @ReactMethod fun addListener(eventName: String) {}
  @ReactMethod fun removeListeners(count: Int) {}

  override fun invalidate() { stopInternal(); super.invalidate() }   // app reload / teardown: never leave the radio on
}
