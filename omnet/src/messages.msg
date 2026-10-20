// One BLE advertising PDU as heard by one receiver (sent from the advertising phone to each phone that decoded it).
message Advert {
    int sender;
    double rssi;
    int channel;
}

// POST /report as the phone sends it. rtt / lostResp / tAttempt let the server model the return path of this attempt.
message ReportMsg {
    int phone;
    int attempt;
    double tAttempt;
    double rtt;
    bool lostResp;
    int peers[];
    int rssi[];
    int counts[];
}

// HTTP answer: ok (200) or refused (4xx: the roll call is over, never retried).
message AckMsg {
    int phone;
    int attempt;
    bool refused;
}
