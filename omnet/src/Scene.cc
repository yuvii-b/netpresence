#include "Scene.h"

#include <omnetpp.h>

#include <fstream>
#include <sstream>

using namespace omnetpp;

static std::vector<std::string> split(const std::string& s, char sep = ',') {
    std::vector<std::string> out;
    std::string cur;
    std::stringstream ss(s);
    while (std::getline(ss, cur, sep)) out.push_back(cur);
    return out;
}

static std::ifstream openOrDie(const std::string& path) {
    std::ifstream f(path);
    if (!f) throw cRuntimeError("cannot open scene file '%s' (run: python -m netsim.omnet_export ...)", path.c_str());
    return f;
}

double Scene::num(const std::string& k) const {
    auto it = kv.find(k);
    if (it == kv.end()) throw cRuntimeError("scene parameter '%s' missing in params.csv", k.c_str());
    return std::stod(it->second);
}

std::string Scene::str(const std::string& k) const {
    auto it = kv.find(k);
    if (it == kv.end()) throw cRuntimeError("scene parameter '%s' missing in params.csv", k.c_str());
    return it->second;
}

void Scene::load(const std::string& d) {
    dir = d;
    std::string line;
    {
        auto f = openOrDie(d + "/params.csv");
        while (std::getline(f, line)) {
            if (line.empty() || line[0] == '#') continue;
            auto p = line.find(',');
            kv[line.substr(0, p)] = line.substr(p + 1);
        }
    }
    {
        auto f = openOrDie(d + "/phones.csv");
        std::getline(f, line);   // header: idx,id,x,y,inside,seed,platform,rx,tx,adv_ms,scan_eff,tap_s
        while (std::getline(f, line)) {
            if (line.empty()) continue;
            auto c = split(line);
            PhoneRow r;
            r.id = c[1]; r.x = std::stod(c[2]); r.y = std::stod(c[3]);
            r.inside = c[4] == "1"; r.seed = c[5] == "1"; r.ios = c[6] == "ios";
            r.rx = std::stod(c[7]); r.tx = std::stod(c[8]); r.advMs = std::stod(c[9]); r.scanEff = std::stod(c[10]);
            r.tap = std::stod(c[11]);
            phones.push_back(r);
        }
    }
    N = (int)phones.size();
    {
        auto f = openOrDie(d + "/matrix.csv");
        M.reserve((size_t)N * N);
        while (std::getline(f, line)) {
            if (line.empty()) continue;
            for (auto& v : split(line)) M.push_back(std::stof(v));
        }
        if ((int)M.size() != N * N) throw cRuntimeError("matrix.csv has %d values, expected %d", (int)M.size(), N * N);
    }
    {
        auto f = openOrDie(d + "/profiles.csv");
        std::getline(f, line);
        while (std::getline(f, line)) {
            if (line.empty()) continue;
            auto c = split(line);
            Profile p;
            p.name = c[0]; p.shared = c[1] == "1"; p.rttMs = std::stod(c[2]); p.rttSigma = std::stod(c[3]);
            p.loss = std::stod(c[4]); p.capMbps = std::stod(c[5]); p.alpha = std::stod(c[6]); p.stallP = std::stod(c[7]);
            p.blackout = c[8] == "1";
            profiles.push_back(p);
        }
    }
    for (auto& item : split(str("uplink_mix"), ';')) {     // "wifi_good:0.7;cell_4g:0.3"
        auto p = item.find(':');
        mix.push_back({item.substr(0, p), p == std::string::npos ? 1.0 : std::stod(item.substr(p + 1))});
    }
    {
        auto f = openOrDie(d + "/bytes.csv");
        std::getline(f, line);
        while (std::getline(f, line)) {
            if (line.empty()) continue;
            reportBytes.push_back(std::stoi(split(line)[1]));
        }
    }
}
