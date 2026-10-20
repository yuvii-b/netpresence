// One phone: tap -> radio on -> advertise + scan -> NeighbourCollector -> signed report -> upload with the app's retry ladder.
#pragma once
#include <omnetpp.h>

#include <map>
#include <vector>

#include "BleMedium.h"
#include "Scene.h"
#include "messages_m.h"

using namespace omnetpp;

class Server;

class Phone : public cSimpleModule {
  public:
    int idx = 0;
    PhoneRow row;
    bool joined = false;
    double onMs = 0, endMs = 0;

    bool listeningOn(double tMs, int ch) const;

  protected:
    enum { TAP = 1, ADV_EVENT, PDU_START, PDU_END, SCAN_END, UPLOAD, TIMEOUT, RETRY };
    int numInitStages() const override { return 2; }
    void initialize(int stage) override;
    void handleMessage(cMessage* m) override;
    void finish() override;

  private:
    BleMedium* medium = nullptr;
    Server* server = nullptr;
    cMessage* ev = nullptr;
    double phase = 0, itv = 1, win = 1;
    double advEventS = 0;                 // start of the current advertising event (s)
    int curCh = 0;
    std::map<int, std::vector<int>> samples;               // NeighbourCollector: peer -> rounded RSSI samples
    std::map<int, double> dirOffset;                       // persistent per-direction offset (dir_sigma) [dB]
    std::map<int, double> lastReportMs;                    // iOS coalescing
    std::map<int, bool> pairDropped;
    // report + upload
    std::vector<int> rPeers, rRssi, rCounts;
    int attempt = 0, profile = 0;
    double delayS = 0, deadlineS = 0;
    bool done = false;
    long adverts = 0;

    void startPdu(int ch);
    void buildReport();
    void doAttempt();
    void colour(const char* c);
};
