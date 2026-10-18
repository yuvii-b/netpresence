#include "BleMedium.h"

#include <cmath>

#include "Phone.h"

Define_Module(BleMedium);

static inline double lin(double db) { return std::pow(10.0, db / 10.0); }

void BleMedium::initialize(int stage) {
    if (stage == 0) {
        scene.load(par("sceneDir").stdstringValue());
        airtimeMs = scene.num("airtime_ms");
        ifsMs = scene.num("airtime_ms") + scene.num("t_ifs_adv_ms");
        sensitivity = scene.num("sensitivity");
        ricianK = std::pow(10.0, scene.num("rician_k_db") / 10.0);
        capture = scene.num("capture") != 0;
        captureDb = scene.num("capture_db");
        pBg[0] = scene.num("p_bg_37"); pBg[1] = scene.num("p_bg_38"); pBg[2] = scene.num("p_bg_39");
    }
}

void BleMedium::begin(int snd, int ch, double startMs) {
    recent.push_back({startMs, snd, ch});
    while (!recent.empty() && recent.front().startMs < startMs - 4 * airtimeMs) recent.pop_front();
    nPdu++;
}

void BleMedium::finishPdu(int snd, int ch, double t, std::vector<Hit>& out) {
    const double tau = airtimeMs;
    std::vector<const Pdu*> ov;                       // PDUs overlapping this one in time (any channel)
    for (auto& q : recent)
        if (!(q.snd == snd && q.ch == ch && q.startMs == t) && std::fabs(q.startMs - t) < tau) ov.push_back(&q);
    const int N = scene.N;
    const double txS = scene.phones[snd].tx;
    for (int r = 0; r < N; r++) {
        if (r == snd) continue;
        Phone* pr = phones[r];
        if (!pr->joined || t < pr->onMs) continue;
        const float m0 = scene.mean(snd, r);
        if (m0 < -150) continue;                       // hopeless pair: never audible
        if (!pr->listeningOn(t, ch)) { nNotListening++; continue; }
        bool blocked = false;
        double interf = 0;
        int nint = 0;
        for (auto* q : ov) {
            if (q->snd == r) blocked = true;           // half duplex: it was transmitting itself
            if (q->ch == ch) {
                double pw = scene.mean(q->snd, r) + scene.phones[q->snd].tx + scene.phones[r].rx;
                interf += lin(pw);
                if (pw > sensitivity) nint++;
            }
        }
        if (blocked) { nHalfDuplex++; continue; }
        // per-PDU Rician fading around the mean
        double mean = m0 + txS + scene.phones[r].rx;
        double re = std::sqrt(ricianK / (ricianK + 1)) + std::sqrt(0.5 / (ricianK + 1)) * normal(0, 1);
        double im = std::sqrt(0.5 / (ricianK + 1)) * normal(0, 1);
        double rssi = mean + 20.0 * std::log10(std::sqrt(re * re + im * im) + 1e-12);
        bool lost;
        if (capture) lost = interf > 0 && (rssi - 10.0 * std::log10(std::max(interf, 1e-30))) < captureDb;
        else lost = nint > 0;
        if (lost) { nCollided++; continue; }
        if (uniform(0, 1) < pBg[ch]) { nBackground++; continue; }
        if (rssi <= sensitivity) { nWeak++; continue; }
        if (uniform(0, 1) >= scene.phones[r].scanEff) { nOsDrop++; continue; }
        nDelivered++;
        out.push_back({r, rssi});
    }
}

void BleMedium::finish() {
    recordScalar("pdus", nPdu);
    recordScalar("delivered", nDelivered);
    recordScalar("collided", nCollided);
    recordScalar("halfDuplex", nHalfDuplex);
    recordScalar("background", nBackground);
    recordScalar("belowSensitivity", nWeak);
    recordScalar("notListening", nNotListening);
    recordScalar("osDropped", nOsDrop);
}
