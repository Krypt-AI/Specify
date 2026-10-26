from app.db import session as db_session
from app.models import Integration
from tests.conftest import login_as, make_user


def test_users_only_see_their_own_integrations(client):
    alice = make_user("alice@example.com", "a")
    bob = make_user("bob@example.com", "b")
    with db_session.SessionLocal() as db:
        db.add(Integration(user_id=alice.id, provider="gmail"))
        db.commit()

    login_as(client, bob)
    gmail = next(i for i in client.get("/api/integrations").json() if i["provider"] == "gmail")
    assert gmail["connected"] is False
    assert client.delete("/api/integrations/gmail").status_code == 404


def test_settings_merge_and_stay_per_user(client):
    alice = make_user("alice@example.com", "a")
    bob = make_user("bob@example.com", "b")

    login_as(client, alice)
    client.put("/api/settings", json={"preferences": {"timezone": "Asia/Kuala_Lumpur"}})
    response = client.put(
        "/api/settings", json={"preferences": {"draft_tone": "formal"}, "setup_completed": True}
    )
    preferences = response.json()["preferences"]
    assert preferences["timezone"] == "Asia/Kuala_Lumpur"
    assert preferences["draft_tone"] == "formal"

    login_as(client, bob)
    me = client.get("/api/auth/me").json()
    assert me["preferences"]["timezone"] is None
    assert me["setup_completed"] is False


def test_settings_reject_invalid_values(client):
    login_as(client, make_user("alice@example.com", "a"))
    assert client.put("/api/settings", json={"preferences": {"timezone": "Mars/Base"}}).status_code == 422
    response = client.put(
        "/api/settings", json={"preferences": {"classification": {"auto_apply_threshold": 0.1}}}
    )
    assert response.status_code == 422


def test_settings_merge_nested_sections(client):
    login_as(client, make_user("alice@example.com", "a"))
    client.put("/api/settings", json={"preferences": {"university": {"domains": [" UM.edu.my "]}}})
    response = client.put("/api/settings", json={"preferences": {"university": {"keywords": ["FYP"]}}})
    university = response.json()["preferences"]["university"]
    assert university["domains"] == ["um.edu.my"]
    assert university["keywords"] == ["fyp"]
