#!/usr/bin/env bash
set -euo pipefail

VIDEO_DIR="${VIDEO_DIR:-bird_videos}"
TARGET_BYTES="${TARGET_BYTES:-3500000}"
AUDIO_KBPS="${AUDIO_KBPS:-64}"
MAX_WIDTH="${MAX_WIDTH:-640}"
MIN_VIDEO_KBPS="${MIN_VIDEO_KBPS:-180}"
PRESET="${PRESET:-slow}"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg is required" >&2
  exit 1
fi

if ! command -v ffprobe >/dev/null 2>&1; then
  echo "ffprobe is required" >&2
  exit 1
fi

if [ ! -d "$VIDEO_DIR" ]; then
  echo "Video directory does not exist: $VIDEO_DIR" >&2
  exit 1
fi

shopt -s nullglob
videos=("$VIDEO_DIR"/*.mp4)
if [ "${#videos[@]}" -eq 0 ]; then
  echo "No .mp4 files found in $VIDEO_DIR" >&2
  exit 1
fi

timestamp="$(date +%Y%m%d_%H%M%S)"
backup_dir="${BACKUP_DIR:-${VIDEO_DIR}_originals_${timestamp}}"
work_dir="$(mktemp -d "${TMPDIR:-/tmp}/bird-video-recompress.XXXXXX")"
pass_dir="$work_dir/passlogs"
out_dir="$work_dir/out"
mkdir -p "$pass_dir" "$out_dir"

cleanup() {
  rm -rf "$work_dir"
}
trap cleanup EXIT

probe_value() {
  local input="$1"
  local entries="$2"
  ffprobe -v error -select_streams v:0 -show_entries "$entries" \
    -of default=noprint_wrappers=1:nokey=1 "$input" | sed -n '1p'
}

has_audio() {
  local input="$1"
  local codec
  codec="$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_type \
    -of default=noprint_wrappers=1:nokey=1 "$input" | sed -n '1p')"
  [ "$codec" = "audio" ]
}

calc_initial_video_kbps() {
  local input="$1"
  local duration="$2"
  local audio_kbps="$3"
  local source_video_bps
  source_video_bps="$(probe_value "$input" stream=bit_rate || true)"

  awk -v target="$TARGET_BYTES" \
      -v duration="$duration" \
      -v audio="$audio_kbps" \
      -v source="$source_video_bps" \
      -v min="$MIN_VIDEO_KBPS" '
    BEGIN {
      target_kbps = int(((target - 160000) * 8 / duration / 1000) - audio - 24)
      source_kbps = source > 0 ? int(source / 1000 * 0.75) : target_kbps
      cap_kbps = 900
      kbps = target_kbps
      if (source_kbps > 0 && source_kbps < kbps) kbps = source_kbps
      if (cap_kbps < kbps) kbps = cap_kbps
      if (kbps < min) kbps = min
      print kbps
    }'
}

validate_output() {
  local output="$1"
  local input_size="$2"
  local size
  local video_codec
  local pix_fmt
  local audio_codec

  size="$(stat -f%z "$output")"
  if [ "$size" -ge "$TARGET_BYTES" ]; then
    echo "Output exceeds target: $output is $size bytes, target is <$TARGET_BYTES" >&2
    return 1
  fi
  if [ "$size" -ge "$input_size" ]; then
    echo "Output is not smaller than original: $output is $size bytes, original is $input_size" >&2
    return 1
  fi

  video_codec="$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name \
    -of default=noprint_wrappers=1:nokey=1 "$output" | sed -n '1p')"
  pix_fmt="$(ffprobe -v error -select_streams v:0 -show_entries stream=pix_fmt \
    -of default=noprint_wrappers=1:nokey=1 "$output" | sed -n '1p')"
  audio_codec="$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_name \
    -of default=noprint_wrappers=1:nokey=1 "$output" | sed -n '1p')"

  if [ "$video_codec" != "h264" ]; then
    echo "Unexpected video codec for $output: $video_codec" >&2
    return 1
  fi
  if [ "$pix_fmt" != "yuv420p" ]; then
    echo "Unexpected pixel format for $output: $pix_fmt" >&2
    return 1
  fi
  if [ -n "$audio_codec" ] && [ "$audio_codec" != "aac" ]; then
    echo "Unexpected audio codec for $output: $audio_codec" >&2
    return 1
  fi
}

encode_video() {
  local input="$1"
  local output="$2"
  local basename="$3"
  local duration="$4"
  local input_size="$5"
  local audio_flags=()
  local audio_kbps=0
  local video_kbps
  local width="$MAX_WIDTH"
  local passlog="$pass_dir/$basename"

  if has_audio "$input"; then
    audio_flags=(-c:a aac -b:a "${AUDIO_KBPS}k")
    audio_kbps="$AUDIO_KBPS"
  else
    audio_flags=(-an)
  fi

  video_kbps="$(calc_initial_video_kbps "$input" "$duration" "$audio_kbps")"

  for attempt in 1 2 3 4 5; do
    rm -f "${passlog}"-0.log "${passlog}"-0.log.mbtree "$output"

    ffmpeg -hide_banner -loglevel error -y -i "$input" \
      -map "0:v:0" -map "0:a?" \
      -vf "scale='min(${width},iw)':-2:flags=lanczos,fps=24" \
      -c:v libx264 -preset "$PRESET" -profile:v main -level 3.1 \
      -pix_fmt yuv420p -b:v "${video_kbps}k" \
      -pass 1 -passlogfile "$passlog" \
      -an -f mp4 /dev/null

    ffmpeg -hide_banner -loglevel error -y -i "$input" \
      -map "0:v:0" -map "0:a?" \
      -vf "scale='min(${width},iw)':-2:flags=lanczos,fps=24" \
      -c:v libx264 -preset "$PRESET" -profile:v main -level 3.1 \
      -pix_fmt yuv420p -b:v "${video_kbps}k" \
      "${audio_flags[@]}" \
      -movflags +faststart -map_metadata -1 \
      -pass 2 -passlogfile "$passlog" \
      "$output"

    if validate_output "$output" "$input_size"; then
      return 0
    fi

    video_kbps="$(awk -v kbps="$video_kbps" -v min="$MIN_VIDEO_KBPS" 'BEGIN { next = int(kbps * 0.72); if (next < min) next = min; print next }')"
    case "$attempt" in
      1) width=560 ;;
      2) width=480 ;;
      3) width=426 ;;
      4) width=360 ;;
    esac
  done

  echo "Could not produce a validated smaller output for $input" >&2
  return 1
}

echo "Recompressing ${#videos[@]} videos from $VIDEO_DIR"
echo "Target: <$TARGET_BYTES bytes each"
echo "Temporary output: $out_dir"

for input in "${videos[@]}"; do
  name="$(basename "$input")"
  output="$out_dir/$name"
  duration="$(ffprobe -v error -show_entries format=duration \
    -of default=noprint_wrappers=1:nokey=1 "$input")"
  input_size="$(stat -f%z "$input")"

  if ! awk -v duration="$duration" 'BEGIN { exit !(duration > 0) }'; then
    echo "Invalid duration for $input: $duration" >&2
    exit 1
  fi

  printf 'Encoding %-45s %10d bytes -> ' "$name" "$input_size"
  encode_video "$input" "$output" "${name%.mp4}" "$duration" "$input_size"
  output_size="$(stat -f%z "$output")"
  printf '%10d bytes\n' "$output_size"
done

if [ -e "$backup_dir" ]; then
  echo "Backup path already exists: $backup_dir" >&2
  exit 1
fi

echo "Creating backup: $backup_dir"
mkdir -p "$backup_dir"
cp -p "$VIDEO_DIR"/*.mp4 "$backup_dir"/

echo "Replacing originals in $VIDEO_DIR"
cp -p "$out_dir"/*.mp4 "$VIDEO_DIR"/

echo "Done. Originals are in $backup_dir"
