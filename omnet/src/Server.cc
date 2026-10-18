#include "Server.h"

#include <cstdlib>
#include <fstream>
#include <sstream>

#include "Phone.h"

Define_Module(Server);

double Server::carry(const Profile& p, double tReady, double bits, double rtt) {
    if (p.shared) {
        while (!inflight.empty() && inflight.top() <= tReady) inflight.pop();
        double cap = p.capMbps * 1e6 / (1.0 + p.alpha * (double)inflight.size());
        double begin = std::max(tReady, mediumFree);
        mediumFree = begin + bits / cap;
        inflight.push(mediumFree);
        return mediumFree + rtt / 2;
    }
    return tReady + bits / (p.capMbps * 1e6) + rtt / 2;
}

void Server::initialize(int stage) {
    if (stage == 0) return;
    medium = check_and_cast<BleMedium*>(getParentModule()->getSubmodule("medium"));
    const Scene& sc = medium->scene;
    deadlineS = sc.num("window_s") + sc.num("tail_s") + sc.num("grace_s");
    verifyS = sc.num("verify_ms") / 1000.0;
    evalMsg = new cMessage("evaluate", EVALUATE);
    scheduleAt(deadlineS + 0.001, evalMsg);
    getDisplayString().setTagArg("i", 0, "device/pc2");
    getDisplayString().setTagArg("p", 0, 60 + sc.num("room_w") * 30);
    getDisplayString().setTagArg("p", 1, 30);
    getDisplayString().setTagArg("t", 0, "server + teacher");
    drawRoom();
}

void Server::drawRoom() {
    const Scene& sc = medium->scene;
    cCanvas* cv = getParentModule()->getCanvas();
    const double S = 60.0, X0 = 60.0, Y0 = 90.0;
    double w = sc.num("room_w"), d = sc.num("room_d"), wallX = sc.num("wall_x");
    const double top = Y0 - 30, bottom = Y0 + (d + 0.5) * S, wallPx = X0 + wallX * S;
    auto* room = new cRectangleFigure("room");
    room->setBounds(cFigure::Rectangle(X0 - 30, top, wallX * S + 30, bottom - top));
    room->setLineColor(cFigure::GREY);
    room->setFilled(false);
    cv->addFigure(room);
    double y0 = sc.num("door_y0"), y1 = sc.num("door_y1");
    auto addWall = [&](double a, double b) {
        auto* l = new cLineFigure("wall");
        l->setStart(cFigure::Point(wallPx, a));
        l->setEnd(cFigure::Point(wallPx, b));
        l->setLineWidth(4);
        l->setLineColor(cFigure::BLACK);
        cv->addFigure(l);
    };
    if (y0 < 0) addWall(top, bottom);
    else { addWall(top, Y0 + y0 * S); addWall(Y0 + y1 * S, bottom); }
    (void)w;
    auto* tt = new cLabelFigure("title");
    tt->setText("NetPresence roll call (OMNeT++)");
    tt->setPosition(cFigure::Point(X0, 10));
    cv->addFigure(tt);
}

void Server::handleMessage(cMessage* m) {
    if (m->getKind() == EVALUATE) {
        evalMsg = nullptr;
        evaluate();
        delete m;
        return;
    }
    auto* r = check_and_cast<ReportMsg*>(m);
    attempts++;
    double now = simTime().dbl();
    double begin = std::max(now, serverFree);
    serverFree = begin + verifyS;
    auto* ack = new AckMsg("ack");
    ack->setPhone(r->getPhone());
    ack->setAttempt(r->getAttempt());
    Phone* ph = medium->phones[r->getPhone()];
    if (serverFree > deadlineS) {                   // refused: the roll call is over (4xx, never retried)
        refused++;
        ack->setRefused(true);
        sendDirect(ack, 0.0, 0, ph, "radioIn");
        delete m;
        return;
    }
    if (!reports.count(r->getPhone())) {
        Rep rep;
        for (size_t i = 0; i < r->getPeersArraySize(); i++) {
            rep.peers.push_back(r->getPeers(i)); rep.rssi.push_back(r->getRssi(i)); rep.counts.push_back(r->getCounts(i));
        }
        rep.at = serverFree;
        reports[r->getPhone()] = rep;
        lastDelivered = std::max(lastDelivered, serverFree);
    }
    double ackAt = serverFree + r->getRtt() / 2;
    bool success = !r->getLostResp() && (ackAt - r->getTAttempt()) <= medium->scene.num("request_timeout_ms") / 1000.0;
    if (success) sendDirect(ack, std::max(0.0, ackAt - now), 0, ph, "radioIn");
    else delete ack;
    delete m;
}

void Server::evaluate() {
    if (evaluated) return;
    evaluated = true;
    const Scene& sc = medium->scene;
    std::string dir = par("outDir").stdstringValue();
    if (dir.empty()) dir = sc.dir;
    {
        std::ofstream f(dir + "/reports.csv");
        f << "reporter,peer,rssi_median,sample_count\n";
        for (auto& kv : reports)
            for (size_t i = 0; i < kv.second.peers.size(); i++)
                f << sc.phones[kv.first].id << ',' << sc.phones[kv.second.peers[i]].id << ',' << kv.second.rssi[i] << ',' << kv.second.counts[i] << '\n';
        std::ofstream c(dir + "/checkins.csv");
        c << "id\n";
        for (auto* p : medium->phones) if (p->joined) c << p->row.id << '\n';
        std::ofstream r(dir + "/reporters.csv");
        r << "id\n";
        for (auto& kv : reports) r << sc.phones[kv.first].id << '\n';
    }
    std::string cmd = par("evalCommand").stdstringValue();
    if (cmd.empty()) {
        EV_WARN << "evalCommand is empty: reports written to " << dir << ", no verdict\n";
        return;
    }
    cmd += " --dir \"" + dir + "\"";
    EV_INFO << "running the real engine: " << cmd << "\n";
    int rc = std::system(cmd.c_str());
    if (rc != 0) error("the engine call failed (exit %d): %s", rc, cmd.c_str());

    std::set<std::string> present;
    std::vector<std::pair<std::string, std::string>> edges, colocated;
    {
        std::ifstream f(dir + "/verdict.csv");
        if (!f) error("no verdict.csv in %s", dir.c_str());
        std::string line;
        while (std::getline(f, line)) {
            std::stringstream ss(line);
            std::string kind, a, b;
            std::getline(ss, kind, ','); std::getline(ss, a, ','); std::getline(ss, b, ',');
            if (kind == "P") present.insert(a);
            else if (kind == "E") edges.push_back({a, b});
            else if (kind == "C") colocated.push_back({a, b});
        }
    }
    std::map<std::string, Phone*> byId;
    for (auto* p : medium->phones) byId[p->row.id] = p;
    std::set<std::string> flagged;
    for (auto& c : colocated) flagged.insert(c.first);
    for (auto* p : medium->phones) {
        const bool in = p->row.inside, seed = p->row.seed;
        const bool pres = present.count(p->row.id) > 0 || seed;
        if (in && !seed) { inside++; if (!pres) falseAbsent++; }
        if (!in) { outside++; if (pres) falsePresent++; }
        if (pres) presentTotal++;
        const char* col = pres ? "limegreen" : flagged.count(p->row.id) ? "orange" : (p->joined ? "red" : "grey");
        p->getDisplayString().setTagArg("i", 1, col);
        p->getDisplayString().setTagArg("i", 2, 70);
    }
    cCanvas* cv = getParentModule()->getCanvas();
    for (auto& e : edges) {                               // the proximity graph the engine built
        if (!byId.count(e.first) || !byId.count(e.second)) continue;
        auto pa = byId[e.first]->row, pb = byId[e.second]->row;
        auto* l = new cLineFigure("edge");
        l->setStart(cFigure::Point(60 + pa.x * 60, 90 + pa.y * 60));
        l->setEnd(cFigure::Point(60 + pb.x * 60, 90 + pb.y * 60));
        l->setLineColor(cFigure::Color(120, 180, 120));
        l->setLineOpacity(0.5);
        cv->addFigure(l);
    }
    bubble(("present " + std::to_string(presentTotal)).c_str());
    EV_INFO << "VERDICT: inside " << inside << " false-absent " << falseAbsent << " outside " << outside << " false-present " << falsePresent << "\n";
}

void Server::finish() {
    recordScalar("inside", inside);
    recordScalar("falseAbsent", falseAbsent);
    recordScalar("outside", outside);
    recordScalar("falsePresent", falsePresent);
    recordScalar("present", presentTotal);
    recordScalar("reportsDelivered", (double)reports.size());
    recordScalar("uploadAttempts", attempts);
    recordScalar("refused", refused);
    recordScalar("lastReportAt", lastDelivered);
}
