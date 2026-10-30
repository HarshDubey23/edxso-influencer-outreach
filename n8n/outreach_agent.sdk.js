// n8n Workflow SDK source for "Outreach Agent" (created in n8n through its MCP server).
// Form -> start a live search on the self-hosted server -> poll progress -> fetch results -> email an HTML report.
import { workflow, node, trigger, ifElse, newCredential, expr } from '@n8n/workflow-sdk';

// Credential "Outreach Engine API key" (Custom Auth): {"headers":{"x-api-key":"<API_TOKEN from the server .env>"}}

const form = trigger({
  type: 'n8n-nodes-base.formTrigger',
  version: 2.6,
  config: {
    name: 'Outreach Request',
    parameters: {
      formTitle: 'Find creators and reach out',
      formDescription: 'Describe your brand. The outreach engine searches YouTube now, filters and scores creators, finds published emails, writes a personal email and DM for each, and sends test emails from your connected Gmail. A full report comes to your inbox when it finishes (usually 5-10 minutes).',
      formFields: {
        values: [
          { fieldLabel: 'Brand', fieldName: 'brand', fieldType: 'text', placeholder: 'TrailKit', requiredField: true },
          { fieldLabel: 'What you sell and who you want to reach', fieldName: 'brief', fieldType: 'textarea', placeholder: 'Trail running shoes for runners in India; want trail running and hiking creators', requiredField: true },
          { fieldLabel: 'Region', fieldName: 'region', fieldType: 'dropdown', fieldOptions: { values: [{ option: 'IN' }, { option: 'US' }, { option: 'GB' }, { option: 'AE' }, { option: 'SG' }, { option: 'AU' }, { option: 'CA' }] }, requiredField: true },
          { fieldLabel: 'Test emails to send (0-10)', fieldName: 'send', fieldType: 'number', defaultValue: '3', requiredField: true },
          { fieldLabel: 'Email the report to', fieldName: 'report_to', fieldType: 'email', requiredField: true }
        ]
      },
      responseMode: 'onReceived',
      options: {
        buttonLabel: 'Search and run',
        respondWithOptions: { values: { respondWith: 'text', formSubmittedText: 'Started. The engine is searching now; the report will arrive by email when it finishes.' } }
      }
    }
  }
});

const config = node({
  type: 'n8n-nodes-base.set',
  version: 3.4,
  config: {
    name: 'Server',
    parameters: {
      mode: 'manual',
      includeOtherFields: true,
      assignments: { assignments: [
        { id: 'server-url', name: 'server', value: 'https://YOUR-SERVER.sslip.io', type: 'string' }
      ] }
    }
  }
});

const startRun = node({
  type: 'n8n-nodes-base.httpRequest',
  version: 4.5,
  config: {
    name: 'Start Live Search',
    parameters: {
      method: 'POST',
      url: expr('{{ $json.server }}/api/live/run'),
      authentication: 'genericCredentialType',
      genericAuthType: 'httpTemplatedCustomAuth',
      sendBody: true,
      contentType: 'json',
      specifyBody: 'json',
      jsonBody: expr('{{ JSON.stringify({ name: $json.brand, brief: $json.brief, region: $json.region, language: "en", send: Math.max(0, Math.min(10, Number($json.send) || 0)) }) }}'),
      options: { timeout: 30000 }
    },
    credentials: { httpTemplatedCustomAuth: newCredential('Outreach Engine API key') }
  }
});

const pause = node({
  type: 'n8n-nodes-base.wait',
  version: 1.1,
  config: { name: 'Wait 30s', parameters: { resume: 'timeInterval', amount: 30, unit: 'seconds' } }
});

const status = node({
  type: 'n8n-nodes-base.httpRequest',
  version: 4.5,
  config: {
    name: 'Check Progress',
    parameters: {
      method: 'GET',
      url: expr("{{ $('Server').first().json.server }}/api/live/status"),
      authentication: 'genericCredentialType',
      genericAuthType: 'httpTemplatedCustomAuth',
      options: { timeout: 30000 }
    },
    credentials: { httpTemplatedCustomAuth: newCredential('Outreach Engine API key') }
  }
});

const stillRunning = ifElse({
  version: 2.2,
  config: {
    name: 'Still Running?',
    parameters: {
      conditions: {
        options: { caseSensitive: true, leftValue: '', typeValidation: 'strict' },
        conditions: [{ leftValue: expr('{{ $json.status }}'), operator: { type: 'string', operation: 'equals' }, rightValue: 'running' }],
        combinator: 'and'
      }
    }
  }
});

const results = node({
  type: 'n8n-nodes-base.httpRequest',
  version: 4.5,
  config: {
    name: 'Get Results',
    parameters: {
      method: 'GET',
      url: expr("{{ $('Server').first().json.server }}/api/live/results"),
      authentication: 'genericCredentialType',
      genericAuthType: 'httpTemplatedCustomAuth',
      options: { timeout: 60000 }
    },
    credentials: { httpTemplatedCustomAuth: newCredential('Outreach Engine API key') }
  }
});

const report = node({
  type: 'n8n-nodes-base.code',
  version: 2,
  config: {
    name: 'Build Report',
    parameters: {
      mode: 'runOnceForAllItems',
      language: 'javaScript',
      jsCode: `const r = $input.first().json;
const s = r.state || {};
const esc = (v) => String(v ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const rows = (r.rows || []).filter((x) => x.status === 'qualified');
const server = $('Server').first().json.server;
const line = (x) => '<tr><td><a href="' + esc(x.url) + '">' + esc(x.name) + '</a></td><td>' + x.followers + '</td><td>' + Number(x.engagement_rate).toFixed(1) + '%</td><td>' + esc(x.email && x.email !== 'Not Found' ? x.email : '-') + '</td><td>' + esc(x.sent ? x.sent.status + ' to ' + x.sent.delivered_to : x.message ? x.message.review : '') + '</td></tr>';
const head = s.status === 'error'
  ? '<p><b>The run stopped:</b> ' + esc(s.error) + '</p>'
  : '<p>' + esc(s.queries) + ' searches, ' + esc(s.discovered) + ' channels found, <b>' + esc(s.qualified) + ' qualified</b>, ' + esc(s.emails) + ' published emails, ' + esc(s.messages) + ' messages written, <b>' + esc(s.sent) + ' test emails sent</b>.</p>';
const html = '<h2>' + esc(r.campaign ? r.campaign.name : s.name) + '</h2>' + head +
  '<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;font:14px sans-serif"><tr><th>Creator</th><th>Subscribers</th><th>Engagement</th><th>Email</th><th>Status</th></tr>' +
  rows.slice(0, 50).map(line).join('') + '</table>' +
  '<p>Full results, messages and rejected profiles with reasons: <a href="' + esc(server) + '/live.html">' + esc(server) + '/live.html</a></p>';
return [{ json: { subject: (s.status === 'error' ? 'Outreach run stopped: ' : 'Outreach results: ') + (r.campaign ? r.campaign.name : s.name), html } }];`
    }
  }
});

const mail = node({
  type: 'n8n-nodes-base.gmail',
  version: 2.2,
  config: {
    name: 'Email Report',
    parameters: {
      resource: 'message',
      operation: 'send',
      sendTo: expr("{{ $('Outreach Request').first().json.report_to }}"),
      subject: expr('{{ $json.subject }}'),
      emailType: 'html',
      message: expr('{{ $json.html }}'),
      options: { appendAttribution: false }
    },
    credentials: { gmailOAuth2: { id: 'OBrRYO2kltR7H70B', name: 'Gmail account 2' } }
  }
});

export default workflow('outreach-agent', 'Outreach Agent: search, write, send, report')
  .add(form)
  .to(config)
  .to(startRun)
  .to(pause)
  .to(status)
  .to(stillRunning
    .onTrue(pause)
    .onFalse(results.to(report.to(mail))));
