# Good first issues, ready to open

Open each as a GitHub issue with the label `good first issue` (plus the extra label in brackets). Keep the text short
and say exactly which file to change. A newcomer should be able to finish one in an evening.

1. **Native speaker review: Spanish** (`translation`). Read `leadhound/dashboard/locales/es.json` and
   `leadhound/i18n/es.py` and fix anything that sounds machine-translated. Keep every `{placeholder}`. The tests check
   placeholders: `python -m unittest discover -s tests -t tests`.
2. **Native speaker review: Portuguese (Brazil)** (`translation`). Same as above for `pt`.
3. **Native speaker review: Georgian** (`translation`). Same for `ka`.
4. **Native speaker review: Arabic, including right-to-left layout** (`translation`). Same for `ar`; also report any
   screen where the layout looks wrong right-to-left.
5. **Add Italian** (`translation`). Copy `locales/en.json` and `i18n/en.py` to `it`, translate, add `"it"` to
   `LANGUAGES` in `leadhound/langs.py`. Italian requests are already recognised in posts.
6. **Add a profession: "Tutor / teacher"**. Add a `Profession` in `leadhound/profiles.py` with skills, Freelancer.com
   categories that return projects (check `https://www.freelancer.com/rss/job_<Category>.xml`) and subreddits; add
   `prof.tutor` to every locale and `o.tutor` to every `i18n/<lang>.py`.
7. **Website check: flag a missing favicon** (severity 1). In `analyze_html` in `leadhound/audit.py`, plus a pitch line
   a shop owner understands, translated keys `t.no_favicon`/`f.no_favicon`, and a test in `tests/test_audit.py`.
8. **Website check: flag a missing `lang` attribute on `<html>`** (severity 1), same steps as above.
9. **CLI: `leadhound followups`** prints the leads with a follow-up due (use `Store.followups_due`), like
   `leadhound list`. Add a test in `tests/test_app.py`.
10. **Keyboard shortcut `f` on the Leads screen writes a follow-up** for a contacted lead (see `onKey` and
    `followupBox` in `leadhound/dashboard/leads.js`), and document it in the README.
11. **Suggest a lead source** (`source`, `help wanted`). Comment with public places where clients in your field post
    requests. The best ones become new sources.

Pinned issues to open as well:

- "Native speakers: help fix translations" (link issues 1–5).
- "Which lead source should we add next?" (a poll-style issue; link the `source` issue form).
