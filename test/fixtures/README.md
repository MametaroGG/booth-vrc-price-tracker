# BOOTH search boundary fixture

`booth-search-past-end.html` is reduced from the public rendered DOM observed on 2026-10-07 at about 17:31 UTC:

https://booth.pm/ja/browse/3D%E3%83%A2%E3%83%87%E3%83%AB?sort=new&tags%5B%5D=VRChat&type=digital&page=3055

The requested page was 3055. BOOTH showed 183,215 matching products and a last-page link to 3054, an empty result-card list, and no explicit empty-search message. It still rendered a `rel="next"` link to 3056; absence of a next link is therefore not a valid end-of-results test.

The title, search heading, result count and results-grid subtree are copied from the observed DOM. A minimal document/container wrapper replaces unrelated navigation, recommendations, scripts and personal/browser-specific elements. This is a real DOM-derived regression fixture, not the exact HTTP body received by the earlier failed Actions run. No extra BOOTH request is needed to run tests.
