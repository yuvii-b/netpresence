#include "Phone.h"

#include <algorithm>
#include <cmath>

#include "Server.h"

Define_Module(Phone);

static inline int jsRound(double x) { return (int)std::floor(x + 0.5); }

static int medianOf(std::vector<int> s) {
    std::sort(s.begin(), s.end());
    size_t m = s.size() >> 1;
    return (s.size() % 2) ? s[m] : jsRound((s[m - 1] + s[m]) / 2.0);
}

void Phone::colour(const char* c) { getDisplayString().setTagArg("i", 1, c); }

bool Phone::listeningOn(double t, int ch) const {
    if (t > endMs) return false;
    double x = t - phase;
    double k = std::floor(x / itv);
    int chanNow = (((long)k % 3) + 3) % 3;
    double within = x - itv * k;
    return chanNow == ch && within < win;
}

void Phone::initialize(int stage) {
    if (stage == 0) return;
    idx = getIndex();
    medium = check_and_cast<BleMedium*>(getParentModule()->getSubmodule("medium"));
    server = check_and_cast<Server*>(getParentModule()->getSubmodule("server"));
    const Scene& sc = medium->scene;
    if (idx == 0) medium->phones.assign(sc.N, nullptr);
    medium->phones[idx] = this;
    row = sc.phones[idx];
    double window = sc.num("window_s"), tail = sc.num("tail_s");
    endMs = (window + tail) * 1000.0;
    deadlineS = window + tail + sc.num("grace_s");
    double itvMs = row.ios ? sc.num("ios_scan_dwell_ms") : sc.num("android_scan_interval_ms");
    double winMs = row.ios ? sc.num("ios_scan_dwell_ms") : sc.num("android_scan_window_ms");
    itv = itvMs; win = winMs;
    phase = uniform(0, 1) * itv;

    double sc_px = 60.0;
    getDisplayString().setTagArg("p", 0, 60 + row.x * sc_px);
    getDisplayString().setTagArg("p", 1, 90 + row.y * sc_px);
    getDisplayString().setTagArg("i", 0, "device/cellphone_s");
    colour(row.inside ? "grey" : "darkgrey");
    getDisplayString().setTagArg("i", 2, 60);
    getDisplayString().setTagArg("t", 0, row.seed ? "seed" : "");

    // a lognormal tap delay (median, log-sd), unless the scene fixes it (attackers tap at once)
    double tap = row.tap >= 0 ? row.tap : sc.num("tap_median_s") * std::exp(sc.num("tap_sigma") * normal(0, 1));
    if (sc.num("tap_median_s") <= 0 && row.tap < 0) tap = 0;
    if (tap <= window) {
        joined = true;
        onMs = (tap + sc.num("startup_s")) * 1000.0;
        scheduleAt(tap, new cMessage("tap", TAP));
        double adv = row.advMs;
        advEventS = onMs / 1000.0 + uniform(0, adv) / 1000.0;
        scheduleAt(advEventS, new cMessage("advEvent", ADV_EVENT));
        scheduleAt(window + tail, new cMessage("scanEnd", SCAN_END));
    } else {
        onMs = 1e18;
    }
    // uplink profile for this phone (weighted draw)
    double u = uniform(0, 1), acc = 0, tot = 0;
    for (auto& m : sc.mix) tot += m.second;
    profile = 0;
    for (size_t i = 0; i < sc.mix.size(); i++) {
        acc += sc.mix[i].second / tot;
        if (u <= acc) { for (size_t k = 0; k < sc.profiles.size(); k++) if (sc.profiles[k].name == sc.mix[i].first) profile = (int)k; break; }
    }
}

void Phone::startPdu(int ch) {
    const Scene& sc = medium->scene;
    double nowMs = simTime().dbl() * 1000.0;
    if (nowMs + medium->airtimeMs > endMs) return;          // no more adverts once discovery has ended
    curCh = ch;
    medium->begin(idx, ch, nowMs);
    adverts++;
    scheduleAt(simTime() + medium->airtimeMs / 1000.0, new cMessage("pduEnd", PDU_END));
    (void)sc;
}

void Phone::handleMessage(cMessage* m) {
    const Scene& sc = medium->scene;
    if (auto* a = dynamic_cast<Advert*>(m)) {
        // NeighbourCollector.add: per-direction offset, validity range, JS-style rounding
        int s = a->getSender();
        double v = a->getRssi();
        if (!dirOffset.count(s)) dirOffset[s] = sc.num("dir_sigma") * normal(0, 1);
        v += dirOffset[s];
        double minGap = sc.num("ios_min_report_ms");
        double nowMs = simTime().dbl() * 1000.0;
        bool skip = false;
        if (minGap > 0 && row.ios) {
            auto it = lastReportMs.find(s);
            if (it != lastReportMs.end() && nowMs - it->second < minGap) skip = true;
            else lastReportMs[s] = nowMs;
        }
        if (!skip && v < 0 && v >= -127) samples[s].push_back(jsRound(v));
        delete m;
        return;
    }
    if (auto* k = dynamic_cast<AckMsg*>(m)) {
        if (k->getAttempt() == attempt && !done) {
            done = true;
            if (ev) { cancelAndDelete(ev); ev = nullptr; }
            colour(k->getRefused() ? "orangered" : "skyblue");
        }
        delete m;
        return;
    }
    switch (m->getKind()) {
        case TAP:
            colour("gold");
            bubble("checked in");
            delete m;
            break;
        case ADV_EVENT:
            if (std::string(getDisplayString().getTagArg("i", 1)) == "gold") colour("dodgerblue");
            startPdu(0);
            delete m;
            break;
        case PDU_START:
            startPdu((int)(intptr_t)m->getContextPointer());
            delete m;
            break;
        case PDU_END: {
            double startMs = simTime().dbl() * 1000.0 - medium->airtimeMs;
            std::vector<BleMedium::Hit> hits;
            medium->finishPdu(idx, curCh, startMs, hits);
            for (auto& h : hits) {
                auto* adv = new Advert("adv");
                adv->setSender(idx);
                adv->setRssi(h.rssi);
                adv->setChannel(curCh);
                sendDirect(adv, 0, 0, medium->phones[h.rx], "radioIn");
            }
            if (curCh < 2) {
                auto* nx = new cMessage("pduStart", PDU_START);
                nx->setContextPointer((void*)(intptr_t)(curCh + 1));
                scheduleAt(advEventS + (curCh + 1) * medium->ifsMs / 1000.0, nx);
            } else {
                advEventS += (row.advMs + uniform(0, sc.num("adv_delay_max_ms"))) / 1000.0;
                scheduleAt(advEventS, new cMessage("advEvent", ADV_EVENT));
            }
            delete m;
            break;
        }
        case SCAN_END:
            buildReport();
            delete m;
            break;
        case UPLOAD:
            delayS = sc.num("retry_start_ms") / 1000.0;
            doAttempt();
            delete m;
            break;
        case TIMEOUT: {
            ev = nullptr;
            if (done) { delete m; break; }
            double t = simTime().dbl();
            if (t + delayS > deadlineS) { done = true; delete m; break; }       // gave up: the roll call is over
            ev = new cMessage("retry", RETRY);
            scheduleAt(t + delayS, ev);
            delayS = std::min(delayS * 2, sc.num("retry_max_ms") / 1000.0);
            delete m;
            break;
        }
        case RETRY:
            ev = nullptr;
            doAttempt();
            delete m;
            break;
        default:
            error("unknown message kind %d", m->getKind());
    }
}

void Phone::buildReport() {
    const Scene& sc = medium->scene;
    int minSamples = (int)sc.num("min_samples"), maxN = (int)sc.num("max_neighbours");
    bool calibrate = sc.num("calibrate") != 0;
    struct N { int peer, med, cnt; };
    std::vector<N> list;
    for (auto& kv : samples) {
        if (!pairDropped.count(kv.first)) pairDropped[kv.first] = !(uniform(0, 1) < sc.num("p_detect"));
        if (pairDropped[kv.first]) continue;
        if ((int)kv.second.size() < minSamples) continue;
        list.push_back({kv.first, medianOf(kv.second), (int)kv.second.size()});
    }
    std::sort(list.begin(), list.end(), [&](const N& a, const N& b) {
        if (a.cnt != b.cnt) return a.cnt > b.cnt;
        if (a.med != b.med) return a.med > b.med;
        return sc.phones[a.peer].id < sc.phones[b.peer].id;
    });
    if ((int)list.size() > maxN) list.resize(maxN);
    double off = calibrate ? row.rx + row.tx : 0.0;       // server-side per-model offset table (netsim default: present)
    for (auto& n : list) {
        rPeers.push_back(n.peer);
        rRssi.push_back((int)std::nearbyint(n.med - off));
        rCounts.push_back(n.cnt);
    }
    double ready = sc.num("window_s") + sc.num("tail_s") + 0.05 + uniform(0, 0.2) + uniform(0, 1) * sc.num("upload_jitter_s");
    scheduleAt(ready, new cMessage("upload", UPLOAD));
    colour("mediumpurple");
}

void Phone::doAttempt() {
    const Scene& sc = medium->scene;
    attempt++;
    const Profile& p = sc.profiles[profile];
    double now = simTime().dbl();
    int n = (int)rPeers.size();
    int bytes = sc.reportBytes[std::min<size_t>(n, sc.reportBytes.size() - 1)] + (int)sc.num("http_overhead_bytes");
    double rtt = p.rttMs > 0 ? p.rttMs / 1000.0 * std::exp(normal(0, p.rttSigma)) : 0.0;
    double stall = uniform(0, 1) < p.stallP ? uniform(1, 3) : 0.0;
    double tReady = now + sc.num("conn_rtts") * rtt + stall;
    double tArrive = server->carry(p, tReady, bytes * 8.0, rtt);
    bool lostReq = p.blackout || uniform(0, 1) < p.loss / 2;
    bool lostResp = uniform(0, 1) < p.loss / 2;
    if (!lostReq) {
        auto* r = new ReportMsg("report");
        r->setPhone(idx); r->setAttempt(attempt); r->setTAttempt(now); r->setRtt(rtt); r->setLostResp(lostResp);
        r->setPeersArraySize(n); r->setRssiArraySize(n); r->setCountsArraySize(n);
        for (int i = 0; i < n; i++) { r->setPeers(i, rPeers[i]); r->setRssi(i, rRssi[i]); r->setCounts(i, rCounts[i]); }
        sendDirect(r, std::max(0.0, tArrive - now), 0, server, "in");
    }
    ev = new cMessage("timeout", TIMEOUT);
    scheduleAt(now + sc.num("request_timeout_ms") / 1000.0, ev);
}

void Phone::finish() {
    recordScalar("adverts", adverts);
    recordScalar("peersHeard", (double)samples.size());
}
