#import <React/RCTBridgeModule.h>
#import <React/RCTEventEmitter.h>

/// Secure-Enclave P-256 signing + CoreBluetooth advertise/scan. NOT built in CI (needs Xcode) - see mobile/README.md.
@interface NetPresenceNative : RCTEventEmitter <RCTBridgeModule>
@end
