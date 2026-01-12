import os
print("INTERNAL_API_SECRET set:", bool(os.getenv("INTERNAL_API_SECRET")))
print("REQUIRE_AUTH:", os.getenv("REQUIRE_AUTH"))