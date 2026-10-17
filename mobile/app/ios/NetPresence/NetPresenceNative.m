#import "NetPresenceNative.h"
#import <CoreBluetooth/CoreBluetooth.h>
#import <Security/Security.h>
#import <UIKit/UIKit.h>
#include <sys/utsname.h>

static NSString *const kKeyTag = @"netpresence.device.key";

@interface NetPresenceNative () <CBCentralManagerDelegate, CBPeripheralManagerDelegate>
@property (nonatomic, strong) CBCentralManager *central;
@property (nonatomic, strong) CBPeripheralManager *peripheral;
@property (nonatomic, copy) NSString *advName;
@property (nonatomic, strong) CBUUID *svc;
@property (nonatomic, assign) BOOL running;
@property (nonatomic, assign) BOOL hasListeners;
@end

@implementation NetPresenceNative

RCT_EXPORT_MODULE();

+ (BOOL)requiresMainQueueSetup { return NO; }
- (NSArray<NSString *> *)supportedEvents { return @[ @"NPSample" ]; }
- (void)startObserving { self.hasListeners = YES; }
- (void)stopObserving { self.hasListeners = NO; }

#pragma mark - keys

- (SecKeyRef)copyPrivateKey:(NSError **)err {
  NSData *tag = [kKeyTag dataUsingEncoding:NSUTF8StringEncoding];
  NSDictionary *q = @{
    (id)kSecClass : (id)kSecClassKey, (id)kSecAttrApplicationTag : tag,
    (id)kSecAttrKeyType : (id)kSecAttrKeyTypeECSECPrimeRandom, (id)kSecReturnRef : @YES,
  };
  SecKeyRef key = NULL;
  if (SecItemCopyMatching((__bridge CFDictionaryRef)q, (CFTypeRef *)&key) == errSecSuccess && key) return key;

  // Secure Enclave on real devices; the simulator has none, so fall back to a software key there.
  for (int useSE = 1; useSE >= 0; useSE--) {
    CFErrorRef cfErr = NULL;
    SecAccessControlRef ac = SecAccessControlCreateWithFlags(
        kCFAllocatorDefault, kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly, useSE ? kSecAccessControlPrivateKeyUsage : 0, &cfErr);
    NSMutableDictionary *attrs = [@{
      (id)kSecAttrKeyType : (id)kSecAttrKeyTypeECSECPrimeRandom, (id)kSecAttrKeySizeInBits : @256,
      (id)kSecPrivateKeyAttrs : @{ (id)kSecAttrIsPermanent : @YES, (id)kSecAttrApplicationTag : tag, (id)kSecAttrAccessControl : (__bridge id)ac },
    } mutableCopy];
    if (useSE) attrs[(id)kSecAttrTokenID] = (id)kSecAttrTokenIDSecureEnclave;
    key = SecKeyCreateRandomKey((__bridge CFDictionaryRef)attrs, &cfErr);
    if (ac) CFRelease(ac);
    if (key) return key;
    if (err && !useSE) *err = CFBridgingRelease(cfErr);
  }
  return NULL;
}

RCT_EXPORT_METHOD(publicKey : (RCTPromiseResolveBlock)resolve rejecter : (RCTPromiseRejectBlock)reject) {
  NSError *err = nil;
  SecKeyRef priv = [self copyPrivateKey:&err];
  if (!priv) { reject(@"E_KEY", err.localizedDescription ?: @"key generation failed", err); return; }
  SecKeyRef pub = SecKeyCopyPublicKey(priv);
  CFRelease(priv);
  CFErrorRef cfErr = NULL;
  NSData *point = CFBridgingRelease(SecKeyCopyExternalRepresentation(pub, &cfErr)); // 65-byte X9.63 uncompressed point
  CFRelease(pub);
  if (!point || point.length != 65) { reject(@"E_KEY", @"unexpected public key format", nil); return; }
  // Wrap in an X.509 SubjectPublicKeyInfo header so iOS and Android enrol identically.
  static const uint8_t hdr[] = {0x30, 0x59, 0x30, 0x13, 0x06, 0x07, 0x2a, 0x86, 0x48, 0xce, 0x3d, 0x02, 0x01,
                                0x06, 0x08, 0x2a, 0x86, 0x48, 0xce, 0x3d, 0x03, 0x01, 0x07, 0x03, 0x42, 0x00};
  NSMutableData *spki = [NSMutableData dataWithBytes:hdr length:sizeof(hdr)];
  [spki appendData:point];
  resolve([spki base64EncodedStringWithOptions:0]);
}

RCT_EXPORT_METHOD(sign : (NSString *)message resolver : (RCTPromiseResolveBlock)resolve rejecter : (RCTPromiseRejectBlock)reject) {
  NSError *err = nil;
  SecKeyRef priv = [self copyPrivateKey:&err];
  if (!priv) { reject(@"E_SIGN", err.localizedDescription ?: @"no key", err); return; }
  CFErrorRef cfErr = NULL;
  // X9.62 SHA-256 over the message => ASN.1 DER signature, identical to the Android output.
  NSData *sig = CFBridgingRelease(SecKeyCreateSignature(priv, kSecKeyAlgorithmECDSASignatureMessageX962SHA256,
                                                         (__bridge CFDataRef)[message dataUsingEncoding:NSUTF8StringEncoding], &cfErr));
  CFRelease(priv);
  if (!sig) { reject(@"E_SIGN", @"signing failed", CFBridgingRelease(cfErr)); return; }
  resolve([sig base64EncodedStringWithOptions:0]);
}

RCT_EXPORT_METHOD(deviceModel : (RCTPromiseResolveBlock)resolve rejecter : (RCTPromiseRejectBlock)reject) {
  struct utsname u; uname(&u);
  resolve([NSString stringWithFormat:@"Apple %s", u.machine]); // e.g. "Apple iPhone14,5" - used as the calibration key
}

#pragma mark - radio

RCT_EXPORT_METHOD(startRadio : (NSString *)name serviceUuid : (NSString *)uuid resolver : (RCTPromiseResolveBlock)resolve rejecter : (RCTPromiseRejectBlock)reject) {
  self.advName = name;
  self.svc = [CBUUID UUIDWithString:uuid];
  self.running = YES;
  // Delegates fire on the main queue; state-restoration is deliberately not used (foreground-only by design).
  self.central = [[CBCentralManager alloc] initWithDelegate:self queue:dispatch_get_main_queue()];
  self.peripheral = [[CBPeripheralManager alloc] initWithDelegate:self queue:dispatch_get_main_queue()];
  resolve(nil);
}

RCT_EXPORT_METHOD(stopRadio : (RCTPromiseResolveBlock)resolve rejecter : (RCTPromiseRejectBlock)reject) {
  self.running = NO;
  dispatch_async(dispatch_get_main_queue(), ^{
    [self.central stopScan]; [self.peripheral stopAdvertising];
    self.central = nil; self.peripheral = nil;
  });
  resolve(nil);
}

- (void)emitName:(NSString *)n rssi:(NSNumber *)r {
  if (self.hasListeners) [self sendEventWithName:@"NPSample" body:@{ @"name" : n, @"rssi" : r }];
}

- (void)centralManagerDidUpdateState:(CBCentralManager *)c {
  if (c.state == CBManagerStatePoweredOn && self.running) {
    // AllowDuplicates is mandatory: without it iOS reports each peer once and we get no RSSI series.
    [c scanForPeripheralsWithServices:@[ self.svc ] options:@{CBCentralManagerScanOptionAllowDuplicatesKey : @YES}];
  } else if (c.state == CBManagerStateUnauthorized || c.state == CBManagerStatePoweredOff) {
    [self emitName:[NSString stringWithFormat:@"NP-ERR-CENTRAL-%ld", (long)c.state] rssi:@(-1)];
  }
}

- (void)centralManager:(CBCentralManager *)c didDiscoverPeripheral:(CBPeripheral *)p advertisementData:(NSDictionary<NSString *, id> *)ad RSSI:(NSNumber *)rssi {
  NSString *n = ad[CBAdvertisementDataLocalNameKey]; // iOS peers
  if (![n hasPrefix:@"NP-"]) {
    NSData *m = ad[CBAdvertisementDataManufacturerDataKey]; // Android peers: 0xFFFF company id then ASCII eph
    if (m.length > 2) {
      NSString *eph = [[NSString alloc] initWithData:[m subdataWithRange:NSMakeRange(2, m.length - 2)] encoding:NSASCIIStringEncoding];
      if (eph.length) n = [@"NP-" stringByAppendingString:eph];
    }
  }
  if ([n hasPrefix:@"NP-"]) [self emitName:n rssi:rssi];
}

- (void)peripheralManagerDidUpdateState:(CBPeripheralManager *)p {
  if (p.state == CBManagerStatePoweredOn && self.running) {
    // iOS cannot set TX power or custom payload bytes; LocalName + service UUID is all we get (foreground only).
    [p startAdvertising:@{CBAdvertisementDataLocalNameKey : self.advName, CBAdvertisementDataServiceUUIDsKey : @[ self.svc ]}];
  }
}

@end
