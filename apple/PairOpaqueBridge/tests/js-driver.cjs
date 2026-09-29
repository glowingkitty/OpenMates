// Runs the published JS pairing dependency so the native bridge can prove
// interoperability in both client/server directions.
const fs = require('node:fs');
const path = require('node:path');
const opaque = require(path.resolve(__dirname, '../../../frontend/packages/pairing-crypto/node_modules/@serenity-kit/opaque'));

(async () => {
  await opaque.ready;
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const ids = input.identifiers;
  const ksf = { 'argon2id-custom': { memory: 8192, iterations: 3, parallelism: 1 } };
  let result;
  switch (input.operation) {
    case 'jsRegister': {
      const serverSetup = opaque.server.createSetup();
      const start = opaque.client.startRegistration({ password: input.password });
      const response = opaque.server.createRegistrationResponse({
        serverSetup, userIdentifier: input.userIdentifier, registrationRequest: start.registrationRequest,
      });
      const finish = opaque.client.finishRegistration({
        clientRegistrationState: start.clientRegistrationState,
        registrationResponse: response.registrationResponse,
        password: input.password, identifiers: ids, keyStretching: ksf,
      });
      result = { serverSetup, registrationRecord: finish.registrationRecord };
      break;
    }
    case 'jsStartClient': result = opaque.client.startLogin({ password: input.password }); break;
    case 'jsStartServer': result = opaque.server.startLogin({
      serverSetup: input.serverSetup, registrationRecord: input.registrationRecord,
      startLoginRequest: input.startLoginRequest, userIdentifier: input.userIdentifier, identifiers: ids,
    }); break;
    case 'jsFinishClient': result = opaque.client.finishLogin({
      clientLoginState: input.clientLoginState, loginResponse: input.loginResponse,
      password: input.password, identifiers: ids, keyStretching: ksf,
    }); break;
    case 'jsFinishServer': result = opaque.server.finishLogin({
      serverLoginState: input.serverLoginState, finishLoginRequest: input.finishLoginRequest, identifiers: ids,
    }); break;
    default: throw new Error('unsupported test operation');
  }
  process.stdout.write(JSON.stringify(result));
})().catch(error => { process.stderr.write(String(error)); process.exit(1); });
