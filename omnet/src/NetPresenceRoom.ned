package netpresence;

network NetPresenceRoom
{
    parameters:
        int numPhones;
        @display("bgb=640,640");
    submodules:
        medium: BleMedium { @display("p=560,40"); }
        server: Server { @display("p=330,30"); }
        phone[numPhones]: Phone;
}
