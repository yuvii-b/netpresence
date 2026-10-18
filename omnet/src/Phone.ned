package netpresence;

// A student's phone (Android or iPhone, as described in the scene file).
simple Phone
{
    parameters:
        @display("i=device/cellphone_s");
    gates:
        input radioIn @directIn;
}
