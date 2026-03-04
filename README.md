# Explosion

```bash
uvx git+https://github.com/hammerill/explosion
```

By default, loop playback is anchored to global time via NTP (`time.google.com`) so
multiple devices stay on the same frame.

```bash
# disable global time sync
explosion --no-time-sync

# use a different NTP server
explosion --time-server pool.ntp.org
```
