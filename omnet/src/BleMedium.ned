package netpresence;

// The shared BLE advertising channel (channels 37/38/39): collisions, half duplex, scanner duty cycle, fading.
simple BleMedium
{
    parameters:
        string sceneDir = default("generated/scene");
        @display("i=abstract/wifi;is=s");
}
