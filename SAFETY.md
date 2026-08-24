# Safety and responsible use

## Platform rules

Aeyori is a self-bot: it uses a Discord user account rather than an official bot
account. Discord's rules prohibit automating normal user accounts. Karuta, top.gg,
and server operators may impose additional restrictions. Those services can
change their rules or enforcement at any time.

No timing option, retry strategy, or usage pattern makes an account immune from
detection or enforcement. Aeyori does not promise a particular ban rate.

## Credential safety

A Discord token grants access comparable to a password.

- Store it only in the local Aeyori configuration.
- Never commit it, upload it, paste it into an issue, or send it to support.
- Do not run modified binaries from untrusted sources.
- Rotate the token immediately if it is exposed.
- Remove tokens and personal data before sharing logs or screenshots.

Aeyori's website account and optional Stripe supporter checkout do not need your
Discord user token. The project will never ask you to send that token by email or
through a support ticket.

## Operational limits

Use the independent workflow switches, daily ceilings, and stop control. Do not
use Aeyori to:

- evade enforcement or bypass rate limits;
- defeat CAPTCHAs or other access controls;
- overwhelm Discord, Karuta, top.gg, or another service;
- impersonate, harass, or disadvantage another person;
- automate accounts you do not own or have permission to operate.

## Payments

All functional Aeyori capabilities are free. Optional payments support hosting
and development. Supporter status does not make automation safer, faster, or more
permissible, and it does not grant additional gameplay capabilities.

## Reporting a problem

Open a GitHub issue for code defects that contain no credentials or personal
information. For a security issue, provide a minimal description first and wait
for a secure reporting channel before sending sensitive details.
