"""Shared yt-dlp options for the videos Cinefin downloads (trailers, media)."""

# How yt-dlp ranks the formats it may pick: the highest resolution first (within
# the format string's cap), then H.264 over VP9 and AV1 at that resolution. Its
# own default prefers AV1, which some players cannot decode at all (the 2019
# NVIDIA SHIELD has no AV1 decoder and plays the sound with no picture). YouTube
# serves H.264 up to 1080p, so a 1080p cap gets H.264; above that the choice is
# VP9 or AV1, and VP9 ranks first.
FORMAT_SORT = ["res", "vcodec:h264"]
