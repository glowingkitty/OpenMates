import asyncio
import base64
import hashlib
import time

from backend.core.api.app.routes.auth_routes.signup_transaction import verify_signup_transaction


class Cache:
    def __init__(self, values):
        self.values = values

    async def get(self, key):
        return self.values.get(key)

    async def get_and_delete(self, key):
        return self.values.pop(key, None)


# contract-test: direct surface=rest_api assertions=auth.signup.transaction-bound,auth.signup.access-gates
def test_signup_proof_binds_email_username_invite_and_consumes_once():
    email = "alice@example.test"
    hashed_email = base64.b64encode(hashlib.sha256(email.encode()).digest()).decode()
    token = "verified-client-token"
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    cache = Cache({
        f"email_verified:{hashed_email}": {
            "email": email, "username": "alice", "invite_code": "INVITE",
            "verified_at": int(time.time()), "transaction_token_hash": token_hash,
        },
        f"signup_transaction:{hashed_email}:{token_hash}": 1,  # Redis JSON decoding
    })
    def verify(**kwargs):
        return asyncio.run(verify_signup_transaction(
            cache, hashed_email=hashed_email, username="alice", invite_code="INVITE", **kwargs
        ))
    assert verify(transaction_token="wrong", consume=True) is None
    assert verify(transaction_token=token, consume=True) is not None
    assert verify(transaction_token=token, consume=True) is None


# contract-test: direct surface=rest_api assertions=auth.signup.transaction-bound
def test_signup_proof_rejects_rebound_username():
    email = "alice@example.test"
    hashed_email = base64.b64encode(hashlib.sha256(email.encode()).digest()).decode()
    token = "verified-client-token"
    cache = Cache({f"email_verified:{hashed_email}": {
        "email": email, "username": "alice", "invite_code": "",
        "verified_at": int(time.time()),
        "transaction_token_hash": hashlib.sha256(token.encode()).hexdigest(),
    }})
    assert asyncio.run(verify_signup_transaction(
        cache, hashed_email=hashed_email, username="mallory", invite_code="",
        transaction_token=token,
    )) is None
