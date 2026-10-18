// The shared 2.4 GHz advertising channel: who hears which PDU. All the physics of the link layer lives here.
#pragma once
#include <omnetpp.h>

#include <deque>
#include <vector>

#include "Scene.h"

using namespace omnetpp;

class Phone;

class BleMedium : public cSimpleModule {
  public:
    struct Pdu { double startMs; int snd; int ch; };
    struct Hit { int rx; double rssi; };

    Scene scene;
    std::vector<Phone*> phones;

    double airtimeMs, ifsMs, sensitivity, ricianK, captureDb;
    bool capture;
    double pBg[3];

    void begin(int snd, int ch, double startMs);
    void finishPdu(int snd, int ch, double startMs, std::vector<Hit>& out);

  protected:
    int numInitStages() const override { return 2; }
    void initialize(int stage) override;
    void finish() override;
    void handleMessage(cMessage*) override { error("the medium receives no messages"); }

  private:
    std::deque<Pdu> recent;
    long nPdu = 0, nDelivered = 0, nCollided = 0, nHalfDuplex = 0, nBackground = 0, nWeak = 0, nNotListening = 0, nOsDrop = 0;
};
