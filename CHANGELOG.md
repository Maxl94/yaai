# Changelog

## [1.0.0](https://github.com/Maxl94/yaai/compare/v0.7.0...v1.0.0) (2026-10-17)


### ⚠ BREAKING CHANGES

* **auth:** POST /auth/refresh and POST /auth/logout read the refresh token from the yaai_refresh cookie instead of the request body; the RefreshRequest/LogoutRequest bodies are gone. Login and refresh responses no longer contain refresh_token. POST /auth/oauth/exchange is removed. The refresh rate limit is raised from 10 to 30 per minute because every page load now calls it.
* The AUTO_MIGRATE environment variable has been removed and migrations are no longer applied on server startup. Run `python -m yaai.server.migrate` (or `uv run python -m yaai.server.migrate`) before starting the server and after every upgrade. Docker Compose users must add a one-shot migrate service (see docs/deployment.md); on GCP run the same command as a Cloud Run Job before deploying a new revision.

### Features

* add compare project overview ([#44](https://github.com/Maxl94/yaai/issues/44)) ([77fc3fc](https://github.com/Maxl94/yaai/commit/77fc3fc7e396b1e97cbf103e8ea1b613f10e9439))
* **auth:** keep refresh token in httpOnly cookie, drop OAuth code exchange ([ac0ae5b](https://github.com/Maxl94/yaai/commit/ac0ae5b4e9f700bbdf6f6abde38274984c175eb3))
* **frontend:** add log-scale toggle for distribution charts ([b3bebb0](https://github.com/Maxl94/yaai/commit/b3bebb0a5512038868dcaa55691b39297d9994bb))
* **frontend:** add projects management page ([083f8cb](https://github.com/Maxl94/yaai/commit/083f8cb635fc2b45f3cf626f6a61ea541dcc8740))
* **frontend:** add projects store, API client and project switcher ([776d017](https://github.com/Maxl94/yaai/commit/776d017c0878f48255dfaa3707b5deb1bb5e24c4))
* **frontend:** color dashboard charts by field direction ([f8ed105](https://github.com/Maxl94/yaai/commit/f8ed10548919275e6eb303e286b0c1c3e525448d))
* **frontend:** gate write actions by project role and support model moves ([0bef1ad](https://github.com/Maxl94/yaai/commit/0bef1ad484dbdf18ac45d477ef701a896d6fe62d))
* guard scheduled jobs against multi-instance double execution ([bfd4479](https://github.com/Maxl94/yaai/commit/bfd44790cffe720c6c162d1d7daf16327fbe69a0))
* **projects:** add projects and memberships with migration ([048e260](https://github.com/Maxl94/yaai/commit/048e2603ed3e36aa44b4dc96a81dababe480b6f6))
* **projects:** enforce project-based access control ([3e9d4df](https://github.com/Maxl94/yaai/commit/3e9d4dfaef1a4a529d058381ed1f364a5e24a358))
* require explicit database migrations instead of auto-migrating on startup ([9085a8a](https://github.com/Maxl94/yaai/commit/9085a8aaf9d4faeb3f35cbe8be5fe8cb8cd1ed2b))
* **sdk:** support projects in YaaiClient ([81bfc17](https://github.com/Maxl94/yaai/commit/81bfc1790682ece25878fd363a9a0efa3e12e7c9))
* **security:** add security headers middleware ([ce37984](https://github.com/Maxl94/yaai/commit/ce37984954b0af4650b08212f75c240a8fd274d4))
* **security:** wire hardening into app and document new settings ([5990d80](https://github.com/Maxl94/yaai/commit/5990d8047936820dbd030909e9fd841fdc0db77a))
* **server:** add headless worker for scheduled drift jobs ([2ee28d5](https://github.com/Maxl94/yaai/commit/2ee28d529a543c154670c5b4437ab4f6ee33fa3e))
* track notification read state per user ([b868844](https://github.com/Maxl94/yaai/commit/b8688446751ca2aa11bd2316268a96429a7c6771))


### Bug Fixes

* address simplification review findings ([abe3c22](https://github.com/Maxl94/yaai/commit/abe3c2203ded9368eb32d7f4ef50ef0cbea0041c))
* **auth:** add refresh rotation grace window and address review findings ([d2b8ce8](https://github.com/Maxl94/yaai/commit/d2b8ce88b51d97b6d6c7b2eeeee91f9691792f08))
* **auth:** guard self-demotion and last owner, make password change atomic ([d6ee9d5](https://github.com/Maxl94/yaai/commit/d6ee9d59a5332652f2ae5127d0e2af487030491d))
* **auth:** harden password change, password length, roles and access grants ([cbaf087](https://github.com/Maxl94/yaai/commit/cbaf0872de747903bfb07cfdca968cb69e66ff6c))
* **auth:** purge expired refresh tokens on rotation ([6a89d88](https://github.com/Maxl94/yaai/commit/6a89d88d4c9c21fdc025752b2aacb3593298a8a5))
* **auth:** validate access tokens against the database ([f08e470](https://github.com/Maxl94/yaai/commit/f08e470c660e1b6f59390876f4697f8b48ea4cd8))
* **charts:** width-aware bucket precision and label formatting ([27e3ab9](https://github.com/Maxl94/yaai/commit/27e3ab9f0a6042a6b312e38035eccb783a2ea95d))
* close critical auth and XSS vulnerabilities ([a148a37](https://github.com/Maxl94/yaai/commit/a148a377f24484df61c8859dedacc7f026dfe56b))
* **compose:** build the app image only once in compose stacks ([978a7f5](https://github.com/Maxl94/yaai/commit/978a7f59fe6d879e00576dad638029d87a680583))
* **dashboard:** return empty histogram buckets and use percentile binning with overflow buckets ([9cf472e](https://github.com/Maxl94/yaai/commit/9cf472e19583add51a12722bead4eea227eb5b61))
* flush schema field deletes before re-adding on overwrite ([f6f5723](https://github.com/Maxl94/yaai/commit/f6f572396a4bbce5502d124d7163d203ecb76242))
* **frontend:** anchor log count axis at 1 and test comparison charts ([4e59ac4](https://github.com/Maxl94/yaai/commit/4e59ac45857957894daede8bc09b414e2373a20f))
* **frontend:** gate job actions per project and surface errors ([44ed0db](https://github.com/Maxl94/yaai/commit/44ed0dba84ea9036ea314a5cf5f729136873d9d8))
* **frontend:** move project filter to models page and harden projects store ([5b2d2e7](https://github.com/Maxl94/yaai/commit/5b2d2e7d5e4fff7a5a1b26041fc5920e576e141e))
* **frontend:** readable chart labels, Other bucket and horizontal bars for long categories ([a89d0c7](https://github.com/Maxl94/yaai/commit/a89d0c741ac83b4f1849faa0e4a9a9f204d0537d))
* **frontend:** resolve job permissions via model details and defer project loading until login ([78c76f5](https://github.com/Maxl94/yaai/commit/78c76f5430827c16d51ff774c91ee7bacfdd7af1))
* **migrate:** allow newer schema on rollback and close Cloud SQL connector ([c3e213e](https://github.com/Maxl94/yaai/commit/c3e213ee28964ad1c6d9d88be0d9d79f63250e11))
* **notifications:** set-based mark-all, index layout and new-reader backlog handling ([1bf2842](https://github.com/Maxl94/yaai/commit/1bf2842d745b3a3b8b32f8091170781681e95047))
* parse RATE_LIMIT_ENABLED with env_bool ([9c297d9](https://github.com/Maxl94/yaai/commit/9c297d9b1d97e6b38614cf186ec23571eeb94505))
* **projects:** scope SA auto-grants to default-project fallback and harden project admin rules ([0e0f178](https://github.com/Maxl94/yaai/commit/0e0f178533ede04e76e4a8355db11357e772b152))
* **scheduler:** run locked job on a single connection and reconcile schedules across instances ([49f9358](https://github.com/Maxl94/yaai/commit/49f9358b06c9d04b3f224ecac6cca07b7218ee5a))
* **sdk:** fetch all pages in list_models ([20bbfa0](https://github.com/Maxl94/yaai/commit/20bbfa07db7ddebbf1da74ffc086271733eb2f63))
* **security:** enforce model access when marking notifications read ([ceca7e9](https://github.com/Maxl94/yaai/commit/ceca7e9745678315e7647265099ae97845f7606a))
* **security:** harden rate-limit key, SPA path check and API docs exposure ([cd9082b](https://github.com/Maxl94/yaai/commit/cd9082b52e2a2a533c13f9acad19a38b4fca7cfb))
* **security:** require JWT and session secrets in production ([9d7fe6e](https://github.com/Maxl94/yaai/commit/9d7fe6e28f975c2c2253cc710be2ab2fcd3c08f1))
* **security:** stop logging bootstrap admin password ([eeb88c6](https://github.com/Maxl94/yaai/commit/eeb88c61a06c117d01ccee340fb256cd3acea977))
* **server:** return JSON 404 for unknown API paths instead of the SPA ([a2dc7ad](https://github.com/Maxl94/yaai/commit/a2dc7ad68b242c759a0d319f00c2a1ba07649c06))
* use Dockerfile.dev in E2E compose stack ([29808e2](https://github.com/Maxl94/yaai/commit/29808e2a878aeffbc7ff0ffd9c616493a8021db9))


### Performance Improvements

* **auth:** use SQL subquery for accessible model filtering ([ee22238](https://github.com/Maxl94/yaai/commit/ee2223891c70ac4d61e0512aae6d7c097bcdb7df))


### Documentation

* add LLM metadata monitoring recipe and example script ([2ffdb38](https://github.com/Maxl94/yaai/commit/2ffdb3816b216ae447308223b0a585dc73c03cb1))
* clarify Cloud Run migration job setup ([3a30105](https://github.com/Maxl94/yaai/commit/3a30105cb1394c4c1fc0be44ab8dcd83f20bac1a))
* deduplicate configuration and deployment guidance ([76e0686](https://github.com/Maxl94/yaai/commit/76e0686cd78e8201c99a9afa7a4ecfba60da08bb))
* document projects and access control ([c3d3a59](https://github.com/Maxl94/yaai/commit/c3d3a5986f5a93e5d997093d2f5cf4fb5f744f09))
* make LLM reporter recipe robust and tested ([c12d4fe](https://github.com/Maxl94/yaai/commit/c12d4fe34231faf1c566906fbbd7432d40a4ff49))
* restore Cloud Run scheduler note and add worker to CD example ([66f3a83](https://github.com/Maxl94/yaai/commit/66f3a83c673dc6e011406017c33df2a5c0f4cf85))
* update changelog commit links after history rewrite ([2941e07](https://github.com/Maxl94/yaai/commit/2941e0710b290f77a9c7ab44089d119a9c2ef737))

## [0.7.0](https://github.com/Maxl94/yaai/compare/v0.6.0...v0.7.0) (2026-04-26)


### Features

* implement user deletion functionality with confirmation dialog and error handling along with better error handling ([433affa](https://github.com/Maxl94/yaai/commit/433affa2bbb631de99792b3cb60c10fac54aee28))

## [0.6.0](https://github.com/Maxl94/yaai/compare/v0.5.1...v0.6.0) (2026-04-22)


### Features

* add customizable timeout for YaaiClient initialization ([8da8188](https://github.com/Maxl94/yaai/commit/8da81889029dba0dac9710fd63c947bb6e018c5a))

## [0.5.1](https://github.com/Maxl94/yaai/compare/v0.5.0...v0.5.1) (2026-04-22)


### Bug Fixes

* fix YaaiClient to support ID token retrieval for service accounts and improve credential handling ([df8717b](https://github.com/Maxl94/yaai/commit/df8717b85cacd247ed0f208b187f508336fc14e3))
* fix YaaiClient to support ID token retrieval for service accounts and improve credential handling ([df8717b](https://github.com/Maxl94/yaai/commit/df8717b85cacd247ed0f208b187f508336fc14e3))

## [0.5.0](https://github.com/Maxl94/yaai/compare/v0.4.0...v0.5.0) (2026-03-17)


### Features

* add get_version_by_label method to YaaiClient for version lookup by label and updates documentation and code comments ([011c36d](https://github.com/Maxl94/yaai/commit/011c36d2177dd8c41c98e0383d31b5ea5f1845b7))

## [0.4.0](https://github.com/Maxl94/yaai/compare/v0.3.0...v0.4.0) (2026-03-10)


### Features

* **client:** add get_version and get_or_create_version methods ([09cba5a](https://github.com/Maxl94/yaai/commit/09cba5a44394f0222f54c5849e5ef62192414f05))

## [0.3.0](https://github.com/Maxl94/yaai/compare/v0.2.3...v0.3.0) (2026-02-23)


### Features

* add Google user ID token auth and scale dashboard to 1.8M+ records ([38d581e](https://github.com/Maxl94/yaai/commit/38d581e09ccdcd0e2bd9a4368727f0ef0ab37b96))

## [0.2.3](https://github.com/Maxl94/yaai/compare/v0.2.2...v0.2.3) (2026-02-20)


### Bug Fixes

* add automatic migration on startup ([fb42267](https://github.com/Maxl94/yaai/commit/fb42267a5bd6ed8e599d9c29535599208610e808))
* improves logging ([896aaba](https://github.com/Maxl94/yaai/commit/896aaba393bf64e639cad75c3b26274fa1c73310))

## [0.2.2](https://github.com/Maxl94/yaai/compare/v0.2.1...v0.2.2) (2026-02-20)


### Bug Fixes

* adds default role to role check ([4f91108](https://github.com/Maxl94/yaai/commit/4f911086c1d07ab0b59dd323a148b4751d714c37))

## [0.2.1](https://github.com/Maxl94/yaai/compare/v0.2.0...v0.2.1) (2026-02-20)


### Bug Fixes

* fixes issue with loop for cloud sql iam authentication ([726e185](https://github.com/Maxl94/yaai/commit/726e1853af1c033170523f69bfbf6f101c7e32f6))
* improve warning for default DB credentials to include Cloud SQL connector check ([10efd88](https://github.com/Maxl94/yaai/commit/10efd88e9467d79abe2896b23c826ff83ef139e2))


### Documentation

* adds google service account settings ([3b90f82](https://github.com/Maxl94/yaai/commit/3b90f82097dc9a4ab8e5dd1ac69460cc25a8a0fe))

## [0.2.0](https://github.com/Maxl94/yaai/compare/v0.1.7...v0.2.0) (2026-02-20)


### Features

* add Cloud SQL connector and unify auth/database configuration ([7e6e6ed](https://github.com/Maxl94/yaai/commit/7e6e6ed76974af56bb91b0e7a172e2c7f4207906))

## [0.1.7](https://github.com/Maxl94/yaai/compare/v0.1.6...v0.1.7) (2026-02-19)


### Bug Fixes

* removes rm command in release actions ([804586c](https://github.com/Maxl94/yaai/commit/804586c2d33c8b659dc02b04cd22ea8789013c6a))

## [0.1.6](https://github.com/Maxl94/yaai/compare/v0.1.5...v0.1.6) (2026-02-19)


### Bug Fixes

* adds missing description to dockerfile ([dd9fb82](https://github.com/Maxl94/yaai/commit/dd9fb828fe6f82d40186ff3ba00a33f7225605d3))

## [0.1.5](https://github.com/Maxl94/yaai/compare/v0.1.4...v0.1.5) (2026-02-19)


### Bug Fixes

* adds static files as build artifact ([f94ac78](https://github.com/Maxl94/yaai/commit/f94ac781f4ef162cec50aa631ccaddaa6f6c203a))

## [0.1.4](https://github.com/Maxl94/yaai/compare/v0.1.3...v0.1.4) (2026-02-19)


### Bug Fixes

* adds missing frontend to python wheel and adds dockerfiles for testing ([0a66871](https://github.com/Maxl94/yaai/commit/0a66871d39b52c56d3f3726319d483962c506b0a))

## [0.1.3](https://github.com/Maxl94/yaai/compare/v0.1.2...v0.1.3) (2026-02-19)


### Bug Fixes

* adds missing alembic files to package ([bc7589e](https://github.com/Maxl94/yaai/commit/bc7589e93876afbfe50127acfd59015c2937edb5))

## [0.1.2](https://github.com/Maxl94/yaai/compare/v0.1.1...v0.1.2) (2026-02-19)


### Bug Fixes

* updates alembic configuration and adjusts paths in main.py ([e3daf37](https://github.com/Maxl94/yaai/commit/e3daf379a262d06deeecda93895ac474ae74d44c))

## [0.1.1](https://github.com/Maxl94/yaai/compare/v0.1.0...v0.1.1) (2026-02-16)


### Documentation

* corrects package name ([6acffff](https://github.com/Maxl94/yaai/commit/6acffffaef8a5546c6a1eea4fbe7c3c592867ea2))
* update install commands and fix build for yaai-monitoring rename ([0c28fb6](https://github.com/Maxl94/yaai/commit/0c28fb60078093f18c598185f80832edae00122c))

## [0.1.0](https://github.com/Maxl94/yaai/compare/v0.1.0...v0.1.0) (2026-02-16)


### Features

* initial release of YAAI platform ([ef1633f](https://github.com/Maxl94/yaai/commit/ef1633ff0745d3ec5bcc9701fd71e6811940efd9))


### Documentation

* adds license and contribution guide ([353dec8](https://github.com/Maxl94/yaai/commit/353dec8964d7978a7cf5be19918d014e8922892f))
* adds logo and screenshots ([5170e30](https://github.com/Maxl94/yaai/commit/5170e302b854cae41866a00b6307360322979014))
* adds readme ([58af9f9](https://github.com/Maxl94/yaai/commit/58af9f90744b0eff7d4b7e9522114124af198037))
* updates screenshots ([d493469](https://github.com/Maxl94/yaai/commit/d49346968793a95d9c29d485d1e1b45c74f6c047))


### Miscellaneous Chores

* rename package to align with PyPI ([c18a6b3](https://github.com/Maxl94/yaai/commit/c18a6b3d1b26a8b44e205c6eab7fb6f1d254f979))

## [0.1.0](https://github.com/Maxl94/yaai/compare/v0.1.0...v0.1.0) (2026-02-16)


### Miscellaneous Chores

* rename package to align with PyPI ([c18a6b3](https://github.com/Maxl94/yaai/commit/c18a6b3d1b26a8b44e205c6eab7fb6f1d254f979))

## 0.1.0 (2026-02-16)


### Features

* initial release of YAAI platform ([ef1633f](https://github.com/Maxl94/yaai/commit/ef1633ff0745d3ec5bcc9701fd71e6811940efd9))


### Documentation

* adds license and contribution guide ([353dec8](https://github.com/Maxl94/yaai/commit/353dec8964d7978a7cf5be19918d014e8922892f))
* adds logo and screenshots ([5170e30](https://github.com/Maxl94/yaai/commit/5170e302b854cae41866a00b6307360322979014))
* adds readme ([58af9f9](https://github.com/Maxl94/yaai/commit/58af9f90744b0eff7d4b7e9522114124af198037))
* updates screenshots ([d493469](https://github.com/Maxl94/yaai/commit/d49346968793a95d9c29d485d1e1b45c74f6c047))
