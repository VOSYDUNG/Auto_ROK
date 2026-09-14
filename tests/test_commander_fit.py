from operator_layer.commander_fit import (
    CommanderState,
    PairRecommendation,
    evaluate_pair,
    rank_account_pairs,
)


def test_owned_pair_beats_unowned_meta_pair():
    inventory = {
        "Minamoto no Yoshitsune": CommanderState("Minamoto no Yoshitsune", True, level=60, stars=6),
        "Cao Cao": CommanderState("Cao Cao", True, level=50, stars=5),
    }
    pairs = [
        PairRecommendation("Minamoto no Yoshitsune", "Cao Cao", "BARBARIAN_FORT_RALLY", "S", 0.92),
        PairRecommendation("Qin Shi Huang", "Zhuge Liang", "BARBARIAN_FORT_RALLY", "S_PLUS", 0.99),
    ]

    ranked = rank_account_pairs(pairs, inventory, role="BARBARIAN_FORT_RALLY")

    assert ranked[0].pair.primary == "Minamoto no Yoshitsune"
    assert ranked[0].usable is True
    assert ranked[1].usable is False


def test_specialist_role_downweights_rally_when_operator_is_not_leader():
    inventory = {
        "William Marshal": CommanderState("William Marshal", True, level=60, stars=6),
        "Subutai": CommanderState("Subutai", True, level=60, stars=6),
    }
    pair = PairRecommendation("William Marshal", "Subutai", "RALLY_PVP", "S_PLUS", 0.9)

    fit = evaluate_pair(pair, inventory, operator_role="member")

    assert fit.usable is True
    assert "operator_role_not_specialist" in fit.reasons
    assert fit.score < 0.9


def test_secondary_star_gate_blocks_unready_pair():
    inventory = {
        "Sun Tzu Prime": CommanderState("Sun Tzu Prime", True, level=60, stars=6),
        "Bai Qi": CommanderState("Bai Qi", True, level=20, stars=2),
    }
    pair = PairRecommendation("Sun Tzu Prime", "Bai Qi", "OPEN_FIELD", "S_PLUS", 0.93)

    fit = evaluate_pair(pair, inventory)

    assert fit.usable is False
    assert "secondary_stars<3" in fit.missing
