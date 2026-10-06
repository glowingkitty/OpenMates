"""Synthetic upload-cache regressions; run without services or provider calls.

Complete production coroutine bodies are loaded without unrelated API bootstrap.
REST service-token/allowlist proof remains in the isolated product CI gate.
"""
import ast
import base64
import hmac
import json
import logging
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[2]


def load_functions(path, names, namespace, class_name=None):
    """Execute production functions with only injected I/O and route defaults."""
    tree = ast.parse((ROOT / path).read_text())
    source = tree.body
    if class_name:
        source = next(node.body for node in source if isinstance(node, ast.ClassDef) and node.name == class_name)
    functions = [node for node in source if isinstance(node, ast.AsyncFunctionDef) and node.name in names]
    assert {node.name for node in functions} == set(names)
    for node in functions:
        node.decorator_list = []
        node.args.defaults = [ast.Constant(None) for _ in node.args.defaults]
        node.args.kw_defaults = [ast.Constant(None) if item is not None else None for item in node.args.kw_defaults]
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *functions], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(ROOT / path), 'exec'), namespace)
    return {name: namespace[name] for name in names}


class HTTPError(Exception):
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code = status_code


class Cache:
    def __init__(self, redis):
        self.redis = redis

    @property
    def client(self):
        async def ready():
            return self.redis
        return ready()


class Client:
    def __init__(self, result, status=200):
        self.result, self.status = result, status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, *args, **kwargs):
        return SimpleNamespace(status_code=self.status, json=lambda: self.result)


class UploadCacheOutcomeTests(unittest.IsolatedAsyncioTestCase):
    # contract-test: supporting surface=rest_api assertions=images-view.errors.explicit-failed-result
    async def test_registration_requires_matching_acknowledged_outcome(self):
        for status, result, expected in [
            (200, {'status': 'success', 'embed_id': 'image'}, True),
            (200, {'status': 'preserved', 'embed_id': 'image'}, True),
            (200, {'status': 'skipped', 'reason': 'redis_unavailable'}, False),
            (200, {'status': 'failed'}, False),
            (200, {'status': 'success', 'embed_id': 'other'}, False),
            (200, [], False),
            (503, {'status': 'success', 'embed_id': 'image'}, False),
        ]:
            with self.subTest(status=status, result=result):
                ns = {'logger': logging.getLogger(__name__), 'httpx': SimpleNamespace(AsyncClient=lambda **kw: Client(result, status))}
                function = load_functions('backend/upload/routes/upload_route.py', ['_cache_embed_via_api'], ns)['_cache_embed_via_api']
                acknowledged = await function('https://internal.test', 'synthetic-token', 'image', 'owner', 'wrapped', '', 'https://storage.test', {'original': {'s3_key': 'key'}}, 'image/png', 'Original Image.PNG')
                self.assertEqual(acknowledged, expected)

    # contract-test: supporting surface=rest_api assertions=images-view.errors.explicit-failed-result
    async def test_internal_cache_rejects_unacknowledged_write_and_redis_absence(self):
        ns = {'logger': logging.getLogger(__name__), 'HTTPException': HTTPError}
        function = load_functions('backend/core/api/app/routes/internal_api.py', ['cache_upload_embed'], ns)['cache_upload_embed']
        payload = SimpleNamespace(embed_id='image', user_id='owner', vault_wrapped_aes_key='wrapped', aes_nonce='', s3_base_url='https://storage.test', files={'original': {'s3_key': 'key'}}, content_type='image/png', original_filename='Original Image.PNG', ai_detection=None)
        missing = await function(payload, cache_service=Cache(None))
        self.assertEqual(missing, {'status': 'skipped', 'reason': 'redis_unavailable'})
        redis = SimpleNamespace(get=AsyncMock(return_value=None), set=AsyncMock(return_value=False))
        rejected = await function(payload, cache_service=Cache(redis))
        self.assertEqual(rejected['status'], 'skipped')
        self.assertEqual(rejected['reason'], 'cache_write_unacknowledged')
        redis.set.return_value = True
        accepted = await function(payload, cache_service=Cache(redis))
        self.assertEqual(accepted, {'status': 'success', 'embed_id': 'image'})
        cached = json.loads(redis.set.call_args.args[1])
        self.assertEqual(cached['filename'], 'Original Image.PNG')
        self.assertNotIn('aes_key', cached)


class UploadImageRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def record(self, **changes):
        record = {
            'embed_id': 'image', 'user_id': 'owner', 'created_at': 99000,
            'original_filename': 'Original Image.PNG', 'content_type': 'image/png',
            'files_metadata': {'original': {'s3_key': 'owner/image/original.bin', 'encryption': 'aes-gcm-nonce-prefixed-v1', 'format': 'png'}},
            'vault_wrapped_aes_key': 'vault:v1:synthetic', 'aes_key': 'must-not-return',
            'aes_nonce': '', 's3_base_url': 'https://storage.test',
        }
        return {**record, **changes}

    def route(self):
        ns = {'logger': logging.getLogger(__name__), 'HTTPException': HTTPError, 'time': SimpleNamespace(time=lambda: 100000)}
        return load_functions('backend/core/api/app/routes/internal_api.py', ['resolve_fresh_upload_image'], ns)['resolve_fresh_upload_image']

    async def recover(self, record):
        directus = SimpleNamespace(get_items=AsyncMock(return_value=record))
        result = await self.route()(SimpleNamespace(embed_id='image', user_id='owner'), directus_service=directus)
        return result, directus

    # contract-test: supporting surface=rest_api assertions=images-view.security.server-resolved-decryption,images-view.request.exact-embed-ref
    async def test_fresh_metadata_owner_filter_deadline_and_filename(self):
        result, db = await self.recover([self.record()])
        content = result['content']
        self.assertEqual(content['filename'], 'Original Image.PNG')
        self.assertEqual(content['expires_at'], 185400)
        self.assertEqual(content['files'], self.record()['files_metadata'])
        self.assertNotIn('aes_key', content)
        self.assertNotIn('aes_key', db.get_items.call_args.kwargs['params']['fields'].split(','))
        self.assertEqual(db.get_items.call_args.kwargs['params']['filter'], {'embed_id': {'_eq': 'image'}, 'user_id': {'_eq': 'owner'}})
        self.assertEqual(db.get_items.call_args.kwargs['params']['limit'], 1)
        self.assertTrue(db.get_items.call_args.kwargs['no_cache'])

    # contract-test: supporting surface=rest_api assertions=images-view.security.server-resolved-decryption,images-view.errors.explicit-failed-result
    async def test_wrong_owner_embed_expired_future_invalid_and_oversized_records_denied(self):
        cases = [[], [self.record(), self.record()], [self.record(user_id='other')],
                 [self.record(embed_id='other')], [self.record(created_at=13600)],
                 [self.record(created_at=100001)], [self.record(created_at=True)],
                 [self.record(created_at='99000')], [self.record(created_at=None)],
                 [self.record(files_metadata={str(i): {} for i in range(17)})],
                 [self.record(original_filename='x' * 66000)],
                 [self.record(content_type='application/pdf')], [self.record(vault_wrapped_aes_key='')]]
        for record in cases:
            with self.subTest(record_shape=list(record[0]) if record else []):
                with self.assertRaises(HTTPError) as error:
                    await self.recover(record)
                self.assertEqual(error.exception.status_code, 404)

    def skill(self, app, redis):
        ns = {'logger': logging.getLogger(__name__), 'time': SimpleNamespace(time=lambda: 100000), 'json_lib': json, 'os': SimpleNamespace(environ={})}
        methods = load_functions('backend/apps/images/skills/view_skill.py', ['_lookup_embed_content', '_lookup_fresh_upload_content'], ns, 'ViewSkill')
        skill = SimpleNamespace(app=app)
        for name, function in methods.items():
            setattr(skill, name, types.MethodType(function, skill))
        redis_module = types.ModuleType('redis')
        redis_async = types.ModuleType('redis.asyncio')
        redis_async.from_url = lambda *args, **kwargs: redis
        redis_module.asyncio = redis_async
        return skill, {'redis': redis_module, 'redis.asyncio': redis_async}

    # contract-test: supporting surface=rest_api assertions=images-view.security.server-resolved-decryption,images-view.request.exact-embed-ref
    async def test_cache_miss_recovers_fresh_upload_and_only_remaining_ttl_is_cached(self):
        response, _ = await self.recover([self.record()])
        app = SimpleNamespace(_make_internal_api_request=AsyncMock(return_value=response))
        redis = SimpleNamespace(get=AsyncMock(return_value=None), set=AsyncMock(return_value=True), aclose=AsyncMock())
        skill, modules = self.skill(app, redis)
        with patch.dict(sys.modules, modules):
            content = await skill._lookup_embed_content('image', 'owner-vault-key', user_id='owner')
        self.assertEqual(content['filename'], 'Original Image.PNG')
        self.assertEqual(content['files'], self.record()['files_metadata'])
        app._make_internal_api_request.assert_awaited_once_with('POST', 'internal/uploads/resolve-image', payload={'embed_id': 'image', 'user_id': 'owner'})
        self.assertEqual(redis.set.call_args.kwargs['ex'], 85400)
        redis.aclose.assert_awaited_once()
        self.assertNotIn('aes_key', json.loads(redis.set.call_args.args[1]))

    # contract-test: supporting surface=rest_api assertions=images-view.errors.explicit-failed-result,images-view.security.server-resolved-decryption
    async def test_redis_unavailability_and_unacknowledged_rewarm_do_not_block_durable_recovery(self):
        response, _ = await self.recover([self.record()])
        for redis_error in [False, True]:
            redis = SimpleNamespace(get=AsyncMock(return_value=None, side_effect=ConnectionError() if redis_error else None), set=AsyncMock(return_value=False), aclose=AsyncMock())
            app = SimpleNamespace(_make_internal_api_request=AsyncMock(return_value=response))
            skill, modules = self.skill(app, redis)
            with patch.dict(sys.modules, modules):
                content = await skill._lookup_embed_content('image', 'owner-vault-key', user_id='owner')
            self.assertEqual(content['filename'], 'Original Image.PNG')

    # contract-test: supporting surface=rest_api assertions=images-view.security.server-resolved-decryption,images-view.errors.explicit-failed-result
    async def test_recovery_context_and_original_deadline_are_rechecked_before_cache_write(self):
        response, _ = await self.recover([self.record()])
        for changes in [{'user_id': 'other'}, {'embed_id': 'other'}, {'created_at': 13600, 'expires_at': 100000}, {'created_at': 100001, 'expires_at': 186401}, {'expires_at': 999999}]:
            content = {**response['content'], **changes}
            redis = SimpleNamespace(get=AsyncMock(return_value=None), set=AsyncMock(), aclose=AsyncMock())
            app = SimpleNamespace(_make_internal_api_request=AsyncMock(return_value={'status': 'success', 'content': content}))
            skill, modules = self.skill(app, redis)
            with patch.dict(sys.modules, modules):
                with self.assertRaises(RuntimeError):
                    await skill._lookup_embed_content('image', 'owner-vault-key', user_id='owner')
            redis.set.assert_not_awaited()
        redis = SimpleNamespace(get=AsyncMock(return_value=None), set=AsyncMock(), aclose=AsyncMock())
        app = SimpleNamespace(_make_internal_api_request=AsyncMock())
        skill, modules = self.skill(app, redis)
        with patch.dict(sys.modules, modules):
            with self.assertRaises(RuntimeError) as error:
                await skill._lookup_embed_content('image', 'owner-vault-key')
        self.assertNotIn('expired', str(error.exception))
        app._make_internal_api_request.assert_not_awaited()

    # contract-test: supporting surface=rest_api assertions=images-view.security.server-resolved-decryption
    async def test_cached_wrong_owner_or_expired_recovery_record_is_denied(self):
        response, _ = await self.recover([self.record()])
        for changes in [{'user_id': 'other'}, {'expires_at': 100000}]:
            redis = SimpleNamespace(get=AsyncMock(return_value=json.dumps({**response['content'], **changes})), set=AsyncMock(), aclose=AsyncMock())
            app = SimpleNamespace(_make_internal_api_request=AsyncMock())
            skill, modules = self.skill(app, redis)
            with patch.dict(sys.modules, modules):
                with self.assertRaises(RuntimeError):
                    await skill._lookup_embed_content('image', 'owner-vault-key', user_id='owner')
            app._make_internal_api_request.assert_not_awaited()
            redis.set.assert_not_awaited()

    # contract-test: supporting surface=rest_api assertions=images-view.output.valid-multimodal-result,images-view.security.server-resolved-decryption,images-view.request.exact-embed-ref
    async def test_fresh_durable_recovery_reuses_real_nonce_prefixed_media_reader(self):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from backend.shared.python_utils.media_encryption import decrypt_media_payload, MEDIA_ENCRYPTION_V2
        from backend.shared.python_utils.image_mime import detect_image_mime_type
        response, _ = await self.recover([self.record()])
        app = SimpleNamespace(_make_internal_api_request=AsyncMock(return_value=response))
        redis = SimpleNamespace(get=AsyncMock(return_value=None), set=AsyncMock(return_value=True), aclose=AsyncMock())
        skill, modules = self.skill(app, redis)
        key, nonce = b'k' * 32, b'n' * 12
        plaintext = b'\x89PNG\r\n\x1a\nsynthetic-only-image'
        encrypted = nonce + AESGCM(key).encrypt(nonce, plaintext, None)
        skill._unwrap_aes_key = AsyncMock(return_value=key)
        skill._download_from_s3 = AsyncMock(return_value=encrypted)
        ns = {'logger': logging.getLogger(__name__), 'base64': base64,
              'decrypt_media_payload': decrypt_media_payload, 'MEDIA_ENCRYPTION_V2': MEDIA_ENCRYPTION_V2,
              'detect_image_mime_type': detect_image_mime_type}
        execute = load_functions('backend/apps/images/skills/view_skill.py', ['execute'], ns, 'ViewSkill')['execute']
        with patch.dict(sys.modules, modules):
            output = await execute(skill, 'Original Image.PNG', user_vault_key_id='owner-vault-key',
                                   user_id='owner', file_path_index={'Original Image.PNG': 'image'})
        skill._unwrap_aes_key.assert_awaited_once_with('vault:v1:synthetic', 'owner-vault-key')
        self.assertEqual(output[0], {'type': 'text', 'text': 'Image: Original Image.PNG'})
        self.assertEqual(output[1]['image_url']['url'], 'data:image/png;base64,' + base64.b64encode(plaintext).decode())
        self.assertNotIn('aes_key', json.loads(redis.set.call_args.args[1]))

    # contract-test: supporting surface=rest_api assertions=images-view.security.server-resolved-decryption
    def test_internal_recovery_request_bounds_are_validated_in_body(self):
        from pydantic import BaseModel, Field, ValidationError
        tree = ast.parse((ROOT / 'backend/core/api/app/routes/internal_api.py').read_text())
        model = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'UploadResolveImageRequest')
        ns = {'BaseModel': BaseModel, 'Field': Field}
        exec(compile(ast.Module(body=[model], type_ignores=[]), 'production-upload-request', 'exec'), ns)
        request = ns['UploadResolveImageRequest']
        self.assertEqual(request(embed_id='image', user_id='owner').model_dump(), {'embed_id': 'image', 'user_id': 'owner'})
        for values in [{'embed_id': '', 'user_id': 'owner'}, {'embed_id': 'image', 'user_id': ''},
                       {'embed_id': 'x' * 129, 'user_id': 'owner'}, {'embed_id': 'image', 'user_id': 'x' * 129}]:
            with self.assertRaises(ValidationError):
                request(**values)

    # contract-test: supporting surface=rest_api assertions=images-view.security.server-resolved-decryption
    async def test_existing_internal_service_auth_denies_missing_or_invalid_token(self):
        source = (ROOT / 'backend/core/api/app/routes/internal_api.py').read_text()
        tree = ast.parse(source)
        router = next(node for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'router' for target in node.targets))
        self.assertIn('VerifiedInternalRequest', ast.unparse(router))
        route = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'resolve_fresh_upload_image')
        self.assertIn("router.post('/uploads/resolve-image')", ast.unparse(route.decorator_list[0]))
        ns = {'logger': logging.getLogger(__name__), 'hmac': hmac, 'HTTPException': HTTPError,
              'INTERNAL_API_SHARED_TOKEN': 'synthetic-service-token',
              'status': SimpleNamespace(HTTP_500_INTERNAL_SERVER_ERROR=500, HTTP_401_UNAUTHORIZED=401, HTTP_403_FORBIDDEN=403)}
        auth = load_functions('backend/core/api/app/utils/internal_auth.py', ['verify_internal_token'], ns)['verify_internal_token']
        for headers, code in [({}, 401), ({'X-Internal-Service-Token': 'wrong'}, 403)]:
            with self.assertRaises(HTTPError) as error:
                await auth(SimpleNamespace(headers=headers))
            self.assertEqual(error.exception.status_code, code)
        await auth(SimpleNamespace(headers={'X-Internal-Service-Token': 'synthetic-service-token'}))

    # contract-test: supporting surface=rest_api assertions=images-view.errors.explicit-failed-result
    async def test_embed_cache_false_never_indexes_or_claims_success(self):
        ns = {'logger': logging.getLogger(__name__)}
        function = load_functions('backend/core/api/app/services/cache_chat_mixin.py', ['set_embed_in_cache'], ns, 'ChatCacheMixin')['set_embed_in_cache']
        redis = SimpleNamespace(set=AsyncMock(return_value=False), sadd=AsyncMock(), expire=AsyncMock())
        cache = Cache(redis)
        cache._get_embed_cache_key = lambda value: 'embed:' + value
        cache._get_chat_embed_ids_key = lambda value: 'chat:' + value
        self.assertFalse(await function(cache, 'image', {'encrypted_content': 'wrapped'}, 'chat', ttl=86400))
        redis.sadd.assert_not_awaited()
        redis.expire.assert_not_awaited()
        redis.set.return_value = True
        self.assertTrue(await function(cache, 'image', {'encrypted_content': 'wrapped'}, 'chat', ttl=86400))
        redis.sadd.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
