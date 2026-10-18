// The classroom server + teacher: receives the phones' reports (shared uplink, FIFO verification), and at the report deadline
// hands every report to the REAL engine (backend app.services.graph.evaluate, via netsim.omnet_eval) and shows the verdict.
#pragma once
#include <omnetpp.h>

#include <map>
#include <queue>
#include <set>
#include <vector>

#include "BleMedium.h"
#include "Scene.h"
#include "messages_m.h"

using namespace omnetpp;

class Phone;

class Server : public cSimpleModule {
  public:
    // shared Wi-Fi medium: returns when the request has arrived at the server
    double carry(const Profile& p, double tReady, double bits, double rtt);

  protected:
    enum { EVALUATE = 1 };
    int numInitStages() const override { return 2; }
    void initialize(int stage) override;
    void handleMessage(cMessage* m) override;
    void finish() override;

  private:
    BleMedium* medium = nullptr;
    double mediumFree = 0, serverFree = 0, deadlineS = 0, verifyS = 0;
    std::priority_queue<double, std::vector<double>, std::greater<double>> inflight;
    struct Rep { std::vector<int> peers, rssi, counts; double at; };
    std::map<int, Rep> reports;
    long attempts = 0, refused = 0;
    double lastDelivered = 0;
    bool evaluated = false;
    long inside = 0, falseAbsent = 0, outside = 0, falsePresent = 0, presentTotal = 0;
    cMessage* evalMsg = nullptr;

    void evaluate();
    void drawRoom();
    ~Server() override { cancelAndDelete(evalMsg); }
};
