# Wavebox navigation notes

Observed on 2026-09-27. Recheck current state; these examples may change.

## Verified examples

| Visual group | App label | Assigned space | Observed destination or evidence |
| --- | --- | --- | --- |
| `x@artspaces.net` | `Railway` | `x@artspaces.net` | Railway `livx` project, `dev` environment. |
| `web@artspaces.net` | `Railway` | `web@artspaces.net` | Railway `WebArts` project, `dev` environment. Toolbar marked this space `(Default)`. |
| `x@artspaces.net` | `livxadmin@gmail.com` | `livxadmin@gmail.com` | App Settings confirmed the containing group and assigned space. |

## Inspect group membership and app space

Right-click the Webdock app → **Settings** → **WEBDOCK GROUPS & APPS**.

- **Pick your webdock group** identified the app's containing group.
- The group's **Spaces** section explicitly reported a mix of spaces.
- The expanded app's **Space** section displayed `Using the "…" Space` and its current selector value.

Read these values without editing the selectors, then close the settings window.

## Inspect spaces through the address bar

The `Running the … Space` toolbar button opened a popup with the current space name, **Space used for this app**, **View Apps Using This Space**, and **Space Settings**.

**View Apps Using This Space** opens **Drag & Drop Space Manager**. It lists spaces independently of sidebar groups and highlights the selected space's members. Mixed-space groups have a dashed border. Use **Done** to leave. Dragging a space onto an icon changes its assignment.

The popup's **Open in Space...** is distinct from selecting an existing app in a group. Do not use it merely to find an already configured Railway app.

## Existing persistent apps — October 22, 2026

The owner uses “app,” “tab,” and “shortcut” for persistent Webdock website entries. A page inside an app is a separate tab. During this session, the `x@artspaces.net` visual group contained both `Apple Developer` and `Stripe`; their assigned spaces differed. These observations do not establish current assignments or signed-in accounts. Recheck before account-dependent work, and preserve existing assignments.

Selecting native accessibility `sortable` rows sometimes reordered apps instead of activating them. Use **Global Search**, type the app name into **Search Wavebox and the Web**, and select the matching **Apps → `<name> Weblink`** result only if it is unique or provides enough group/space context. Duplicate identical results require contextual sidebar/settings inspection; do not choose by order. Inspect the resulting toolbar space and website identity. Do not repeatedly click or drag a sortable row when activation fails. An Open Tabs search result did not reliably activate the page in this session; the Apps/Weblink result did.

## Global Search and layouts

**Global Search** opened **Search Wavebox and the Web**. Typing `Railway` returned an open-tab result with its space and two identical `Railway Weblink` app results. `setValue` changed the text without triggering results; clicking the field, selecting its text, and using `typeText` worked. Avoid Enter on an ambiguous result or web suggestion.

**Spaces** layout filters visible groups/apps by space; **List** shows groups across spaces; **Explorer** exposes groups, apps, tabs, and tab folders in a tree. Expand or scroll the current layout. A hidden item is not necessarily absent. Do not change the layout to match an example. See [Wavebox's Webdock layout guide](https://kb.wavebox.io/kb/how-do-i-change-the-webdock-sidebar-layout/).

Wavebox's [Spaces guide](https://kb.wavebox.io/kb/what-are-profiles-and-how-do-i-create-one-in-wavebox-sandboxing/) explains profiles, spaces, and the default space used when opening context is insufficient.
