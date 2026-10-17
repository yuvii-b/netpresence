from app.services.graph import Params, build_edges, evaluate, rssi_to_distance

P = Params(ref_dbm=-59, n=3.0, max_edge_m=3.0, ttl=8, max_path_m=15, k=2, delta_db=8)


def rssi_at(d, p=P):   # forward model, no noise
    import math
    return p.ref_dbm - 10 * p.n * math.log10(d)


def sym(pairs):
    """pairs: {(a,b): metres} -> mutual reports."""
    rep = {}
    for (a, b), d in pairs.items():
        rep.setdefault(a, {})[b] = rssi_at(d)
        rep.setdefault(b, {})[a] = rssi_at(d)
    return rep


def test_distance_inverts_model():
    assert abs(rssi_to_distance(rssi_at(2.5), P) - 2.5) < 1e-9


def test_one_sided_report_is_not_an_edge():
    assert build_edges({"a": {"b": rssi_at(1)}}, P) == {}


def test_far_and_disagreeing_edges_rejected():
    assert build_edges(sym({("a", "b"): 5.0}), P) == {}                        # beyond max_edge_m
    rep = {"a": {"b": rssi_at(1)}, "b": {"a": rssi_at(1) - 20}}              # 20 dB disagreement
    assert build_edges(rep, P) == {}


def test_chain_floods_and_ttl_bounds_it():
    # seed s, then a..e each 2 m apart, each node also sees the next-but-one (so k=2 holds)
    names = ["s", "a", "b", "c", "d", "e"]
    pairs = {}
    for i in range(len(names) - 1):
        pairs[(names[i], names[i + 1])] = 2.0
    for i in range(len(names) - 2):
        pairs[(names[i], names[i + 2])] = 2.9
    rep = sym(pairs)
    full = evaluate(["s"], rep, P)["present"]
    assert {"a", "b", "c", "d"} <= set(full)
    short = evaluate(["s"], rep, Params(**{**P.as_dict(), "ttl": 1, "k": 1}))["present"]
    assert set(short) == {"s", "a", "b"}          # c is 2 hops away (s-b-c): outside TTL=1


def test_path_length_bound():
    names = ["s", "a", "b", "c", "d"]
    pairs = {(names[i], names[i + 1]): 2.5 for i in range(4)}
    out = evaluate(["s"], sym(pairs), Params(**{**P.as_dict(), "k": 1, "max_path_m": 6.0}))["present"]
    assert set(out) == {"s", "a", "b"}   # 2.5, 5.0 in; 7.5 out


def test_k_witness_blocks_single_edge_node():
    rep = sym({("s", "a"): 1.0, ("s", "b"): 1.5, ("a", "b"): 1.0, ("b", "x"): 1.0})
    out = evaluate(["s"], rep, P)["present"]
    assert {"a", "b"} <= set(out) and "x" not in out        # x has 1 witness < k=2


def test_pruning_cascades_to_fixed_point():
    # x and y vouch only for each other plus one real node -> after x drops, y must drop too
    rep = sym({("s", "a"): 1.0, ("s", "b"): 1.0, ("a", "b"): 1.0, ("b", "x"): 1.0, ("x", "y"): 1.0, ("a", "y"): 1.0})
    out = evaluate(["s"], rep, P)["present"]
    # y has witnesses a,x ; x has b,y -> both have 2 admitted edges and survive together (mutual vouching)
    assert "x" in out and "y" in out
    rep2 = sym({("s", "a"): 1.0, ("s", "b"): 1.0, ("a", "b"): 1.0, ("b", "x"): 1.0, ("x", "y"): 1.0})
    out2 = evaluate(["s"], rep2, P)["present"]
    assert "x" not in out2 and "y" not in out2             # y has 1 witness, drops, then x drops


def test_disconnected_node_never_present():
    rep = sym({("s", "a"): 1.0, ("s", "b"): 1.0, ("a", "b"): 1.0, ("p", "q"): 1.0, ("q", "r"): 1.0, ("p", "r"): 1.0})
    out = evaluate(["s"], rep, P)["present"]
    assert not ({"p", "q", "r"} & set(out))
