// Reuse the configured provider module; credentials never cross stdout.
const providerPath = process.argv[2];
const params = JSON.parse(process.argv[3]);
const { call } = require(providerPath);
call('news', 'search_notice', params)
  .then(result => process.stdout.write(JSON.stringify(result)))
  .catch(error => {
    process.stdout.write(JSON.stringify({ok: false, error_type: error.name || 'ProviderError'}));
    process.exitCode = 1;
  });
