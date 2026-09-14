# The human checklist: every click, in order, with a time

For the owner, from tonight's video upload through Monday's Submit. Times are PDT. The laptop session
runs the commands in `docs/reports/FINAL-INTEGRATION.md`; this list is only what a person has to click,
type or decide. The hard cutoff is Monday, September 14, 5:00 PM; the plan submits by noon. The evening
steps carry the minutes each one takes rather than a clock time, so the list holds whenever the evening
starts: the order is what matters, and everything before step 10 can slide into Monday morning as long
as step 14 comes before noon.

## Sunday evening

1. Ten minutes. Code has stopped. Read `make judge` once end to end on the laptop (two to three
   minutes); if it is red, the laptop session fixes it before anything below.
2. Sixty to ninety minutes. Export the video cut from the Saturday footage and the screen recordings listed in
   `docs/video/commands.md` (every on-screen moment has its command and the lines to freeze on;
   `docs/video/storyboard.md` is the one page for the cut: each section's voice lines and its screen
   moments, in order). Run the
   honesty checks at the end of `docs/video-script.md` against the cut: no number on screen that is not in
   `results/`, no live-model shot unless `docs/evidence/live-*.md` exists, Strands named at least three
   times and shown in code once.
3. Fifteen minutes. Upload the video to YouTube. Visibility: Public (the form asks for a public video;
   Public satisfies that reading without a judgement call about Unlisted). Confirm the length is under
   five minutes on the watch page. Copy the URL.
4. Fifteen minutes. Open the pull request from `overnight` to `main` with `docs/SUBMISSION-CHECKLIST.md` as its
   description (the laptop session prepares it; the owner presses Create pull request), read the checks,
   press Merge. The `dispatch-verify` workflow the package places ran green in this layout before the
   merge (`docs/reports/integrated-ci.md`); if it is red on the pull request, the laptop session reads
   that report first, since the difference is the main repo's own Makefile or pyproject.
5. Ten minutes. Repository settings: General, Danger Zone, Change visibility, Public. Then open the
   repository's front page and check the About panel on the right shows "MIT license" (it reads
   `LICENSE` from `main`); if it does not, the LICENSE file is not at the root of `main`, and the laptop
   session fixes that before the form is touched.
6. Ten minutes, plus the workflow's run. Repository settings: Pages, Source: GitHub Actions. The `pages` workflow runs on the merge; when
   it is green, open the site URL it prints (the Actions tab, the `deploy` job) and check the front page
   shows the claims badge and the screenshots. Copy the URL. The workflow audits the site with axe-core
   before it publishes; a red `site-a11y` step means the laptop session runs `make site-a11y`, fixes the
   rule it names, and pushes.
7. Fifteen minutes. Log in to builder.aws.com (OWNER: the login is yours; no one else types a password). Create a
   new post. Paste the title and body of `docs/posts/publish-ready/post-1.md`, fill the two links on its
   last line (the repo URL from step 5, the video URL from step 3), set the tags the form offers from the
   Tags line, press Publish. Copy the post URL.
8. Fifteen minutes. Repeat step 7 for `post-2.md`. Copy the URL.
9. Forty minutes. Log in to Devpost (OWNER). Open the Agents for Humans submission form. Fill every field from
   `docs/reports/forms/devpost-fields.md`: name, tagline, track, description (paste `docs/devpost.md`
   from "Inspiration" to "Screenshots"), Built With tags, the repo URL, the testing instructions, the
   Builder ID email, the disclosure with the last clause confirmed in your own words, the architecture
   diagram and the gallery images from `docs/screenshots/`, the video URL, the two post URLs so far,
   the evidence site URL as the live link until the app URL exists. Save as draft. Do not press Submit
   yet.
10. Sleep. Nothing else tonight; steps 4 to 9 can wait for the morning if the video ran long.

## Monday morning

If the laptop day slid to the morning, `docs/SUNDAY.md` (its last section) is the compressed order:
about two and a half hours for the never-cut items, everything else cut before it starts. It runs
before step 11; step 14 stays at noon at the latest.

11. 8:00 AM. If the laptop's live URL for the rider app exists, paste it into the Devpost form's live
    link field (keep the evidence site URL in the description's Links section) and into the README on
    `main` (the laptop session commits; you press Merge if it is a pull request).
12. 8:30 AM. builder.aws.com: publish `post-3.md` the same way as step 7. Copy the URL. All three posts
    have "Agents for Humans" in the title, as the bonus requires.
13. 8:45 AM. Devpost form: paste the third post URL. Read every field once more against
    `docs/reports/forms/devpost-fields.md`. Open the video URL in a private window to confirm it plays
    without a login and is under five minutes. Open the repo URL in a private window to confirm it is
    public and the About panel shows the license.
14. 9:00 AM. Devpost form: press Submit (OWNER-CLICK). Confirm the submission shows in the gallery.
15. 9:15 AM. Tell the laptop session and the dispatch session it is submitted. Anything after this is a
    post edit on Devpost, allowed until the cutoff, never a code change.

## If something slips

- The video runs long: do steps 4 to 9 anyway with the video URL blank in the draft, and paste it in
  the moment it is up; the form's video field is the only thing waiting on it.
- The About panel does not show the license: the laptop session moves `LICENSE` to the root of `main`;
  the flip to public stays.
- A post form rejects a tag: skip it; the title carrying "Agents for Humans" is what the bonus reads.
- Pages does not publish: the evidence site is not required; leave the live link to the app URL, or
  blank, and say in the description that `make site` builds it locally.
- Any step here is blocked for thirty minutes: skip it, note it in the main repo's day-1.md, continue.
