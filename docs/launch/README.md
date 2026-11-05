# Launch kit

Everything needed to get leadhound in front of people, in the order that tends to work. The posts are drafts:
read them, put them in your own voice, and post them yourself. Nothing here posts anything automatically.

## 1. Before anyone sees it (one evening)

Repository settings on GitHub (Settings tab of the repo):

- [ ] **About** (gear icon on the repo page): website `https://kalidatuna.github.io/leadhound/`, and add topics
      `freelance`, `freelancing`, `lead-generation`, `local-first`, `self-hosted`, `outreach`, `i18n`, `python`,
      `website-audit`, `openstreetmap`.
- [ ] **Social preview**: Settings → General → Social preview → upload `site/social-preview.png` (1280×640).
      This is the picture that shows when the link is shared on X, LinkedIn, Slack, Discord and Hacker News readers.
- [ ] **Discussions**: Settings → General → Features → Discussions. The issue form's "Questions" link points there.
- [ ] **Release 0.5.0**: merge the branch, then publish a GitHub release tagged `v0.5.0` with the CHANGELOG text.
      The release workflow builds the apps, the Docker image and publishes to PyPI. Check that
      `pipx run leadhound demo` works from a clean machine before posting anywhere: every post below links to it.
- [ ] **Good first issues**: open the issues in [good-first-issues.md](good-first-issues.md) and label them
      `good first issue` (and `translation` where it says so). People browsing https://goodfirstissue.dev and
      GitHub's "contribute" pages find projects through that label.
- [ ] Pin 1–2 issues: "Native speakers: help fix translations" and "Which lead source should we add next?".

## 2. Launch week

| Day | Where | Draft | Notes |
|---|---|---|---|
| Tue or Wed, 8–10 am US Eastern | Hacker News: Show HN | [show-hn.md](show-hn.md) | Stay online for 4 hours and answer every comment, especially critical ones. Don't ask friends to upvote: HN detects voting rings and buries the post. |
| Same day, afternoon | r/selfhosted | [reddit.md](reddit.md) | Lead with Docker and local-first. Read the sub's self-promotion rules first. |
| Next day | r/Python | [reddit.md](reddit.md) | Lead with "standard library only, no dependencies" and the build. Showcase posts are welcome there on the right flair. |
| Saturday | r/SideProject, r/webdev (Showoff Saturday) | [reddit.md](reddit.md) | r/webdev only allows project posts on Saturdays. |
| Week after | Product Hunt, Indie Hackers | [launch-sites.md](launch-sites.md) | PH works best with a few people ready to leave genuine comments; schedule for 00:01 Pacific. |
| Ongoing | Freelancer communities in other languages | [local-communities.md](local-communities.md) | The biggest gap: almost every lead tool is English-only. |

Freelancer subreddits (r/freelance, r/forhire, r/Upwork) mostly ban promotion. Don't post there unless a moderator
says yes; answer questions with genuine help instead and mention leadhound only where it fits.

## 3. Keep it going

- **Articles**: [articles/](articles/) has three drafts. Publish one every week or two on dev.to, Hashnode or your own
  site, with a link back. Technical write-ups bring stars long after a launch post has dropped off.
- **Monthly "freelance demand" post**: run `leadhound trends --days 30` at the start of each month and post the table
  ("What clients asked for in October"). It's useful to freelancers on its own and shareable on LinkedIn and Reddit.
- **Changelog posts**: each release gets a short post with one GIF of the new thing.
- **Answer every issue within a day** for the first months. Fast replies turn first users into contributors.
- **Ask for stories**: a pinned Discussion "Clients you won with leadhound" gives you real quotes for the README.

## What to measure

Stars are a proxy. Watch PyPI downloads (pypistats.org/packages/leadhound), release downloads, Gumroad trials and sales,
and how many people open issues or pull requests. Write the numbers down weekly so you know which channel worked.
