---
name: wavebox-browser
description: Open Wavebox apps and tabs in named sidebar groups while verifying their cookie spaces. Use for Wavebox profiles, mixed-space groups, duplicate site tabs, and account-specific navigation.
---

# Wavebox Browser

Use the Computer tool to open the Wavebox app and navigate its sidebar.

## Visual organization and session isolation

| Concept   | Meaning                                                                                                                                                                                                                            | Navigation consequence                                                                                                                                |
| --------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| Profile   | An outer browser profile with its own Wavebox setup, including spaces, groups, apps, and settings.                                                                                                                                 | Use the requested profile when specified. An email-named group or space is not a browser profile.                                                     |
| Space     | A cookie and site-storage partition within a profile. Apps/tabs in the same space share the applicable site's session state; different spaces isolate it. Normal domain/origin boundaries still apply to cookies and localStorage. | The selected app/tab's assigned space determines its session context. A website can still provide its own multi-account switcher within that context. |
| Group     | Visual organization in the sidebar, also called the Webdock. A group has a default space, but its apps/tabs can use different spaces. Visual nesting, folders, and sections do not establish cookie isolation.                     | Resolve a named group through visual membership; verify the selected app/tab's space separately.                                                      |
| App / tab | A named, persistent Webdock app may contain a website and additional tabs. The user may call the app itself a “tab.”                                                                                                               | A sidebar label such as `Railway` can correspond to an extension tab titled `livx` or `WebArts`.                                                      |

Do not model this as a strict Profile → Space → Group → Tab hierarchy. Within a profile, visual placement and space assignment are separate relationships. Even the exact same URL can represent different signed-in sessions.

The user's naming convention is that a group shares its name with its default space, and an email app shares its name with its email address and assigned space. This helps discovery but does not prove every child's space or the website's current account. Read [references/navigation-notes.md](references/navigation-notes.md) for verified examples and alternate inspection routes when needed.

## Open an existing app/tab in a named group

1. **Identify Wavebox and the requested profile.** On macOS, select the native app with `cua.getApp("com.bookry.wavebox")`. Its extension connection may be labeled **Chrome**, with no profile name. Correlate it with Wavebox's visible URL/title and inventory instead of choosing the actual Google Chrome connection.
2. **Find the group and app in the native accessibility tree.** Expand the relevant group/folder or scroll when needed, then select the requested member. Resolve repeated labels within group context. A group header and email app can have identical text. Accessibility may flatten the sidebar into sibling `sortable` rows, so indentation or “first Railway” is not reliable proof of membership. The app-settings route in the reference can confirm membership. Use a targeted screenshot if an unlabeled expander or visual boundary remains unclear.
3. **Wake the existing app if needed.** Selecting a sleeping app can load it and create a fresh extension tab ID. If a sleep placeholder persists, use its observed `Wake it up!` / `Wake App` control and inspect the result. A short or empty extension tab list does not mean sidebar apps are absent. Do not create a replacement merely because a sleeping app is missing from the list.
4. **Verify its space and destination.** Read the native toolbar's `Running the … Space` control. Its popup identifies the space used by the selected app. Check group membership and the loaded page identity too. A group-only request permits that member's existing space to differ from the group name. If the user also specifies a space/account, verify that condition before account-dependent work; a mismatch is not permission to reassign the app or switch accounts.
5. **Bind the matching extension tab.** Refresh `cua.listTabs({ browser: discoveredBrowserId })` after selecting/waking the app. Match the native selected page to its title and full URL, then bind the observed ID with `cua.getTab(observedTabId, { browser: discoveredBrowserId })`. Use the native app's accessibility state for Wavebox's sidebar, spaces, and settings; use the bound tab for website content. Extension listings may omit groups/spaces. If candidates remain indistinguishable, continue through the verified native app instead of guessing an ID.
6. **Leave the requested page selected.** Report its group, observed space, and useful page identity. The site's own account/workspace indicators settle account questions; an email-shaped space name alone does not prove who is signed in.

## New tabs

For a requested new tab in a particular group/space, use Wavebox's contextual UI and verify its resulting space and placement. Do not assume generic browser `new()` / `createBrowserTab()` calls select the requested Wavebox group or space.

---

**Self-reflection and improvement:**
Consider these instructions with your current use case. Can anything be done do to make your job easier? Can we improve these instructions to help make the task easier next time? Edit this skill `skills/wavebox-browser` with any improvements you can think of for next time or suggest possible improvements.
