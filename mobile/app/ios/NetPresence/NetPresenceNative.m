#import "NetPresenceNative.h"
#import <CoreBluetooth/CoreBluetooth.h>
#import <Security/Security.h>
#import <UIKit/UIKit.h>
#include <sys/utsname.h>

static NSString *const kKeyTag = @"netpresence.device.key";

// On air (identical to Android): one advertisement whose 128-bit service UUID ends in the 32-bit ephemeral id.
static NSString *const kPrefix = @"6E657470-7265-7365-6E63-6500";   // CBUUID.UUIDString is upper-case

@interface NetPresenceNative () <CBCentralManagerDelegate, CBPeripheralManagerDelegate>
@property (nonatomic, strong) CBCentralManager *central;
@property (nonatomic, strong) CBPeripheralManager *peripheral;
@property (nonatomic, strong) CBUUID *advUUID;
@property (nonatomic, assign) BOOL running;
@property (nonatomic, assign) BOOL hasListeners;
@property (nonatomic, strong) NSMutableArray<NSDictionary *> *buffer;   // batched to JS every 200 ms
@property (nonatomic, strong) NSTimer *flushTimer;
@end

@implementation NetPresenceNative

RCT_EXPORT_MODULE();

+ (BOOL)requiresMainQueueSetup { return NO; }
- (NSArray<NSString *> *)supportedEvents { return @[ @"NPSamples" ]; }
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

RCT_EXPORT_METHOD(setKeepAwake : (BOOL)on) {
  dispatch_async(dispatch_get_main_queue(), ^{ [UIApplication sharedApplication].idleTimerDisabled = on; });
}

#pragma mark - radio

RCT_EXPORT_METHOD(startRadio : (NSString *)name serviceUuid : (NSString *)uuid resolver : (RCTPromiseResolveBlock)resolve rejecter : (RCTPromiseRejectBlock)reject) {
  NSUUID *parsed = [[NSUUID alloc] initWithUUIDString:uuid];
  if (!parsed || ![parsed.UUIDString hasPrefix:kPrefix]) { reject(@"E_ARG", @"Bad advertise UUID", nil); return; }
  dispatch_async(dispatch_get_main_queue(), ^{
    [self stopInternal];
    self.advUUID = [CBUUID UUIDWithNSUUID:parsed];
    self.buffer = [NSMutableArray array];
    self.running = YES;
    // Delegates fire on the main queue; foreground-only by design (no state restoration, no background modes).
    self.central = [[CBCentralManager alloc] initWithDelegate:self queue:dispatch_get_main_queue()];
    self.peripheral = [[CBPeripheralManager alloc] initWithDelegate:self queue:dispatch_get_main_queue()];
    self.flushTimer = [NSTimer scheduledTimerWithTimeInterval:0.2 target:self selector:@selector(flush) userInfo:nil repeats:YES];
    resolve(nil);
  });
}

RCT_EXPORT_METHOD(stopRadio : (RCTPromiseResolveBlock)resolve rejecter : (RCTPromiseRejectBlock)reject) {
  dispatch_async(dispatch_get_main_queue(), ^{
    [self stopInternal];
    resolve(nil);
  });
}

- (void)stopInternal {   // main queue only
  self.running = NO;
  [self.flushTimer invalidate]; self.flushTimer = nil;
  [self.central stopScan]; [self.peripheral stopAdvertising];
  self.central.delegate = nil; self.peripheral.delegate = nil;
  self.central = nil; self.peripheral = nil;
  [self flush];
}

- (void)invalidate {   // bridge teardown / reload: never leave the radio on
  [super invalidate];  // RCTEventEmitter requires it (NS_REQUIRES_SUPER)
  dispatch_async(dispatch_get_main_queue(), ^{ [self stopInternal]; });
}

- (void)push:(NSString *)n rssi:(NSNumber *)r {
  if (self.buffer.count < 20000) [self.buffer addObject:@{ @"name" : n, @"rssi" : r }];
}

- (void)flush {
  if (self.buffer.count == 0) return;
  NSArray *batch = [self.buffer copy];
  [self.buffer removeAllObjects];
  if (self.hasListeners) [self sendEventWithName:@"NPSamples" body:batch];
}

- (void)centralManagerDidUpdateState:(CBCentralManager *)c {
  if (c.state == CBManagerStatePoweredOn && self.running) {
    // nil services: CoreBluetooth cannot filter on a UUID prefix, so match it below. Foreground scanning with nil
    // services is allowed. AllowDuplicates is mandatory: without it iOS reports each peer once (no RSSI series).
    [c scanForPeripheralsWithServices:nil options:@{CBCentralManagerScanOptionAllowDuplicatesKey : @YES}];
  } else if (c.state == CBManagerStateUnauthorized) {
    [self push:@"NP-ERR-BT-UNAUTHORIZED" rssi:@(-1)];
  } else if (c.state == CBManagerStatePoweredOff) {
    [self push:@"NP-ERR-BT-OFF" rssi:@(-1)];
  } else if (c.state == CBManagerStateUnsupported) {
    [self push:@"NP-ERR-BT-UNSUPPORTED" rssi:@(-1)];
  }
}

- (void)centralManager:(CBCentralManager *)c didDiscoverPeripheral:(CBPeripheral *)p advertisementData:(NSDictionary<NSString *, id> *)ad RSSI:(NSNumber *)rssi {
  NSArray<CBUUID *> *uuids = ad[CBAdvertisementDataServiceUUIDsKey];
  for (CBUUID *u in uuids) {
    NSString *s = u.UUIDString;
    if (s.length == 36 && [s hasPrefix:kPrefix]) {
      // EVERY match is reported: one radio sending two ids is evidence for the server's co-location check
      [self push:[@"NP-" stringByAppendingString:[[s substringFromIndex:kPrefix.length] lowercaseString]] rssi:rssi];
    }
  }
}

- (void)peripheralManagerDidUpdateState:(CBPeripheralManager *)p {
  if (p.state == CBManagerStatePoweredOn && self.running) {
    // Service UUID only - no LocalName - so the whole identity fits in the primary advertisement.
    // iOS cannot set TX power or custom payload bytes (foreground only).
    [p startAdvertising:@{CBAdvertisementDataServiceUUIDsKey : @[ self.advUUID ]}];
  }
}

- (void)peripheralManagerDidStartAdvertising:(CBPeripheralManager *)p error:(NSError *)error {
  if (error) [self push:[NSString stringWithFormat:@"NP-ERR-ADV-%ld", (long)error.code] rssi:@(-1)];
}

@end
