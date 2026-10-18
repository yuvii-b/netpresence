package netpresence;

simple Server
{
    parameters:
        string outDir = default("");
        string evalCommand = default("");   // runs the real engine: python -m netsim.omnet_eval (set by netsim.omnet_run)
        @display("i=device/pc2");
    gates:
        input in @directIn;
}
