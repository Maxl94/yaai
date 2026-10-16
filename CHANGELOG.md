# Changelog

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
