export const init = (root = '/tmp/data-bridge-pi-test') => ({
  id:'init-1', type:'init', provider:'data-bridge-test', model:'fake-model',
  api:'openai-completions', baseUrl:'https://example.invalid/v1', apiKey:'literal-test-key',
  cwd:root, agentDir:`${root}/config`, systemPrompt:'Use only approved bridge tools.',
  tools:[{name:'bridge_echo', description:'Return the supplied text', parameters:{type:'object', properties:{text:{type:'string'}}, required:['text'], additionalProperties:false}}],
  session:{mode:'create', dir:`${root}/sessions`}, toolTimeoutMs:1000,
});
