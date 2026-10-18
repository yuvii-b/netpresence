// Scene description written by backend/netsim/omnet_export.py: the room, the phones and the mean RSSI of every pair.
// The channel (path loss, bodies, wall, shadowing) is computed once in Python by the same code as the Python simulator;
// everything that happens in TIME (advertising, scanning, collisions, tapping, uploading, retries) is simulated here.
#pragma once
#include <map>
#include <string>
#include <vector>

struct PhoneRow {
    std::string id;
    double x = 0, y = 0;
    bool inside = true, seed = false, ios = false;
    double rx = 0, tx = 0, advMs = 100, scanEff = 1, tap = -1;
};

struct Profile {
    std::string name;
    bool shared = false;
    double rttMs = 0, rttSigma = 0, loss = 0, capMbps = 1e6, alpha = 0, stallP = 0;
    bool blackout = false;
};

struct Scene {
    std::map<std::string, std::string> kv;
    std::vector<PhoneRow> phones;
    std::vector<float> M;                 // N x N mean RSSI (before phone gains), -200 = out of range
    std::vector<Profile> profiles;
    std::vector<std::pair<std::string, double>> mix;   // uplink profile mix
    std::vector<int> reportBytes;         // by neighbour count
    int N = 0;
    std::string dir;

    double num(const std::string& k) const;
    std::string str(const std::string& k) const;
    float mean(int i, int j) const { return M[(size_t)i * N + j]; }
    void load(const std::string& dir);
};
