## Entity Name Normalization

Use the simplest, most common name for every entity. The goal is that the same real-world entity always produces the same name string, regardless of how it appears across different records.

- **Companies**: Strip legal suffixes. "Aimhub" not "Aimhub, Inc." or "Aimhub LLC". Drop Inc, LLC, Ltd, Corp, Co, GmbH, S.A., etc. Use the name people actually say in conversation.
- **People**: Use the full formal name. "Michael Chen" not "M. Chen", "Mike", or "michael@acme.com". If only a first name appears, include it only if the person is clearly identifiable from context.
- **Projects**: Use the short working name. "Series A" not "Series A Financing Round". Whatever the team would say in a standup.
- **Events**: Use a descriptive short name. "Acme demo" not "Meeting with Acme Corp, Inc. re: product demonstration".

Do not include domains, emails, or parenthetical qualifiers in entity names — "Acme" not "Acme (acme.com)". That information belongs in metadata.
