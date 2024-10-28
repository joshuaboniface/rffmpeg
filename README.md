

<p align="center">
<img alt="License: GPLv3+" src="https://img.shields.io/github/license/joshuaboniface/rffmpeg"/>
<img alt="Code Style: Black" src="https://img.shields.io/badge/code%20style-black-000000.svg"/>
<a href="https://matrix.to/#/#rffmpeg:matrix.org">
<img alt="Chat on Matrix" src="https://img.shields.io/matrix/rffmpeg:matrix.org.svg?logo=matrix"/>
</a>
<a href="https://www.patreon.com/joshuaboniface">
<img alt="Support me on Patreon" src="https://img.shields.io/endpoint.svg?url=https%3A%2F%2Fshieldsio-patreon.vercel.app%2Fapi%3Fusername%3Djoshuaboniface%26type%3Dpatrons&style=flat"/>
</a>
<a href="https://github.com/sponsors/joshuaboniface">
<img alt="Support me on GitHub" src="https://img.shields.io/github/sponsors/joshuaboniface?label=GitHub%20Sponsors">
</a>
</p>

`rffmpeg` is a remote FFmpeg wrapper used to execute FFmpeg commands on a remote server via SSH. It is most useful in situations involving media servers such as Jellyfin (our reference user), where one might want to perform transcoding actions with FFmpeg on a remote machine or set of machines which can better handle transcoding, take advantage of hardware acceleration, or distribute transcodes across multiple servers for load balancing.

## Quick usage

1. Install the required Python 3 dependencies: `click`, `yaml` and `subprocess` (`sudo apt install python3-click python3-yaml python3-subprocess` in Debian) and optionally install `psycopg2` with `sudo apt install python3-psycopg2` for Postgresql support.

1. Create the directory `/etc/rffmpeg`.

1. Optionally, copy the `rffmpeg.yml.sample` file to `/etc/rffmpeg/rffmpeg.yml` and edit it to suit your needs.

1. Install `rffmpeg` somewhere useful, for instance at `/usr/local/bin/rffmpeg`.

1. Create symlinks for the command names `ffmpeg` and `ffprobe` to `rffmpeg`, for example `sudo ln -s /usr/local/bin/rffmpeg /usr/local/bin/ffmpeg` and `sudo ln -s /usr/local/bin/rffmpeg /usr/local/bin/ffprobe`.

1. Initialize the database and add a target host, for example `sudo rffmpeg init && rffmpeg add myhost.domain.tld`.

1. Set your media program to use `rffmpeg` via the `ffmpeg` symlink name created above, instead of any other `ffmpeg` binary.

1. Profit!

`rffmpeg` does require a little bit more configuration to work properly however. For a comprehensive installation tutorial based on a reference setup, please see [the SETUP guide](SETUP.md).

**NOTE** Jellyfin 10.10.x and newer require an additional `TMPDIR` environment variable set to somewhere exported to the remote machine, or these paths will not work properly. Edit your Jellyfin startup/service configuration to set that. See the setup guide for more details.

## Setup and Usage

### The `rffmpeg` Configuration file

`rffmpeg` will look at `/etc/rffmpeg/rffmpeg.yml` (or a path specified by the `RFFMPEG_CONFIG` environment variable) for a configuration file. If it doesn't find one, defaults will be used instead. You can use this file to override many configurable default values to better fit your environment. The defaults should be sensible for anyone using [Jellyfin](https://jellyfin.org) and following the [SETUP guide](SETUP.md).

The example configuration file at `rffmpeg.yml.sample` shows all available options; this file can be copied as-is to the above location and edited to suit your needs; simply uncomment any lines you want to change. Note that if you do specify a file, you *must* ensure that all top-level categories are present or it will error out.

**NOTE:** If you are running into problems with `rffmpeg`, you must use the config file to adjust `logging` -> `debug` to `true` to obtain more detailed logs before requesting help.

Each option has an explanatory comment above it detailing its purpose.

Since the configuration file is YAML, ensure that you do not use "Tab" characters inside of it, only spaces.

### CLI interface to `rffmpeg`

`rffmpeg` is a [Click](https://click.palletsprojects.com)-based application; thus, all commands have a `-h` or `--help` flag to show usage and additional options that may be specified.

### Initializing `rffmpeg`

After first installing `rffmpeg`, you must initialize the database with the `rffmpeg init` command.

Note that by default, `sudo`/root privilege is required for this command to create the required data paths, but afterwards, `rffmpeg` can be run by anyone in the configured group (by default the `sudo` group). You can bypass the `sudo` requirement with the `--no-root` command, for example when running in a rootless container; this will require the running user to have write permissions to the state and database parent directories, and will not perform any permissions modifications on the resulting files.

### Viewing Status

Once installed and initialized, you can see the status of the `rffmpeg` system with the `rffmpeg status` command. This will show all configured target hosts, their states, and any active commands being run.

### Adding or Removing Target Hosts

To add a target host, use the `rffmpeg add` command. You must add at least one target host for `rffmpeg` to be useful. This command takes the optional `-w`/`--weight` flag to adjust the weight of the target host (see below). A host can also be added more than once for a pseudo-weight, but this is an advanced usage.

To remove a target host, use the `rffmpeg remove` command. This command takes either a target host name/IP, which affects all instances of that name, or a specific host ID. Removing an in-use target host will not terminate any running processes, though it may result in undefined behaviour within `rffmpeg`. Before removing a host it is best to ensure there is nothing using it.

### Viewing the Logfile

The `rffmpeg` CLI offers a convenient way to view the log file. Use `rffmpeg log` to view the entire logfile in the default pager (usually `less`), or use `rffmpeg log -f` to follow any new log entries after that point (like `tail -0 -f`).

## Important Considerations

### Localhost and Fallback

If one of the configured target hosts is called `localhost` or `127.0.0.1`, `rffmpeg` will run the `ffmpeg`/`ffprobe` commands locally without SSH. This can be useful if the local machine is also a powerful transcoding device, but you still want to offload some transcoding jobs to other machines.

In addition, `rffmpeg` will fall back to `localhost` automatically, even if it is not explicitly configured, should it be unable to find any working remote hosts. This helps prevent situations where `rffmpeg` cannot be run due to none of the remote host(s) being available.

The exact path to the local `ffmpeg` and `ffprobe` binaries can be overridden in the configuration, should their paths not match those of the remote system(s).

### Hardware Acceleration

Note that if hardware acceleration is configured in the calling application, **the exact same hardware acceleration modes must be available on all configured hosts, and, for fallback to work, the local host as well**, or the `ffmpeg` commands will fail.

This is an explicit requirement, and there is no easy way around this without rewriting the passed arguments, which is explicitly out-of-scope for `rffmpeg` (see the FAQ entry below about mangling arguments).

You should always use a lowest-common-denominator approach when deciding what hardware acceleration option(s) to enable, such that any configured host can run any process, or accept that fallback will not work if all remote hosts are unavailable.

### Target Host Selection

When more than one target host is present, `rffmpeg` uses the following rules to select a target host. These rules are evaluated each time a new `rffmpeg` alias process is spawned based on the current state (actively running processes, etc.).

1. Any hosts marked `bad` are ignored.

1. All remaining hosts are iterated through in an indeterminate order (Python dictionary with root key as the host ID). For each host:

   a. If the host is not `localhost`/`127.0.0.1`, it is tested to ensure it is reachable (responds to `ffmpeg -version` over SSH). If it is not reachable, it is marked `bad` for the duration of this processes' runtime and skipped.

   b. If the host is `idle` (has no running processes), it is immediately chosen and the iteration stops.

   c. If the host is `active` (has at least one running process), it is checked against the host with the current fewest number of processes, adjusted for host weight. If it has the fewest, it takes over this role.

1. Once all hosts have been iterated through, at least one host should have been chosen: either the first `idle` host, or the host with the fewest number of active processes. `rffmpeg` will then begin running against this host. If no valid target host was found, `localhost` is used (see section [Localhost and Fallback](#localhost-and-fallback) above).

### Target Host Weights and Duplicated Target Hosts

When adding a host to `rffmpeg`, a weight can be specified. Weights are used during the calculation of the fewest number of processes among hosts. The actual number of processes running on the host is floor divided (rounded down to the nearest divisible integer) by the weight to give a "weighted count", which is then used in the determination. This option allows one host to take on more processes than other nodes, as it will be chosen as the "least busy" host more often.

For example, consider two hosts: `host1` with weight 1, and `host2` with weight 5. `host2` would have its actual number of processes floor divided by `5`, and thus any number of processes under `5` would count as `0`, any number of processes between `5` and `10` would count as `1`, and so on, resulting in `host2` being chosen over `host1` even if it had several processes. Thus, `host2` would on average handle 5x more `ffmpeg` processes than `host1` would.

Host weighting is a fairly blunt instrument, and only becomes important when many simultaneous `ffmpeg` processes/transcodes are occurring at once across at least 2 remote hosts, and where the target hosts have significantly different performance profiles. Generally leaving all hosts at weight 1 would be sufficient for most use-cases.

Furthermore, it is possible to add a host of the same name more than once in the `rffmpeg add` command. This is functionally equivalent to setting the host with a higher weight, but may have some subtle effects on host selection beyond what weight alone can do; this is probably not worthwhile but is left in for the option.

### `bad` Hosts

As mentioned above under [Target Host Selection](#target-host-selection), a host can be marked `bad` if it does not respond to an `ffmpeg -version` command in at least 1 second if it is due to be checked as a target for a new `rffmpeg` alias process. This can happen because a host is offline, unreachable, overloaded, or otherwise unresponsive.

Once a host is marked `bad`, it will remain so for as long as the `rffmpeg` process that marked it `bad` is running. This can last anywhere from a few seconds (library scan processes, image extraction) to several tens of minutes (a long video transcode). During this time, any new `rffmpeg` processes that start will see that the host is marked as `bad` and thus skip it for target selection. Once the marking `rffmpeg` process completes or is terminated, the `bad` status of that host will be cleared, allowing the next run to try it again. This strikes a balance between always retrying known-unresponsive hosts over and over (and thus delaying process startup), and ensuring that hosts will eventually be retried.

If for some reason all configured hosts are marked `bad`, fallback will be engaged; see the above section [Localhost and Fallback](#localhost-and-fallback) for details on what occurs in this situation. An explicit `localhost` host entry cannot be marked `bad`.

## FAQ

### Why did you make `rffmpeg`?

My virtualization setup (multiple 1U nodes with lots of live migration/failover) didn't lend itself well to passing a GPU into my Jellyfin VM, but I wanted to offload transcoding because doing 4K HEVC transcodes with a CPU performs horribly. I happened to have another machine (my "base" remote headless desktop/gaming server) which had a GPU, so I wanted to find a way to offload the transcoding to it. I came up with `rffmpeg` as a simple wrapper to the `ffmpeg` and `ffprobe` calls that Jellyfin (and Emby, and likely other media servers too) makes which would run them on that host instead. After finding it quite useful myself, I released it publicly as GPLv3 software so that others may benefit as well! It has since received a lot of feedback and feature requests from the community, leading to the tool as it exists today.

### What supports `rffmpeg`?

This depends on what "layer" you're asking at.

* Media Servers: Jellyfin is officially supported; Emby seems to work fine, with caveats (see [Issue #10](https://github.com/joshuaboniface/rffmpeg/issues/10)); no others have been tested to my knowledge.
* Operating Systems (source): Debian and its derivatives (Ubuntu, Linux Mint, etc.) should all work perfectly; other Linux operating systems should work fine too as the principles are the same; MacOS should work since it has an SSH client built in; Windows will not work as `rffmpeg` depends on some POSIX assumptions internally.
* Operating Systems (target): Any Linux system which [`jellyfin-ffmpeg`](https://github.com/jellyfin/jellyfin-ffmpeg) supports, which is currently just Debian and Ubuntu; Windows *might* work if you can get an SSH server running on it (see [Issue #17](https://github.com/joshuaboniface/rffmpeg/issues/17)).
* Install Methods for Jellyfin: Native packages/installers/archives are recommended; a set of [Jellyfin Docker containers integrating `rffmpeg`](https://github.com/Shadowghost/jellyfin-rffmpeg) has been created by [@Shadowghost](https://github.com/Shadowghost). In addition to this special docker image you can use linuxserver's image with [this mod](https://github.com/linuxserver/docker-mods/tree/jellyfin-rffmpeg).
* Install Methods for `rffmpeg`: Direct installation is recommended; a [Docker container to act as an ffmpeg transcode target](https://github.com/aleksasiriski/rffmpeg-worker) has been created by [@aleksasiriski](https://github.com/aleksasiriski) as well as [another](https://github.com/BasixKOR/rffmpeg-docker) by [@BasixKOR](https://github.com/BasixKOR).
* OUTDATED Cloud: [HCloud Rffmpeg](https://github.com/aleksasiriski/hcloud-rffmpeg) script made to read rffmpeg database and spin up more transcode nodes in Hetzner Cloud.
* Kubernetes: A short guide and example yaml files are available [here](https://github.com/aleksasiriski/rffmpeg-worker/tree/main/Kubernetes).

### Can `rffmpeg` mangle/alter FFMPEG arguments?

Explicitly *no*. `rffmpeg` is not designed to interact with the arguments that the media server passes to `ffmpeg`/`ffprobe` at all, nor will it.

This is an explicit design decision due to the massive complexity of FFmpeg. FFmpeg has a very large number of possible arguments, many of which are position-dependent or dependent on other arguments elsewhere in the chain. To implement argument mangling, we would need to be aware of every possible FFmpeg argument, exactly how each argument maps to each other argument, and be able to dynamically parse and update arguments based on this. As should hopefully be quite obvious, this is a massive undertaking and not something that I have any desire to implement or manage in such a (relatively) simple utility.

This has a number of effects:

 * `rffmpeg` cannot adjust any `ffmpeg` options based on the host selected.
 * `rffmpeg` does not know whether hardware acceleration is turned on or not (see above caveats under [Hardware Acceleration](#hardware-acceleration)), or what type(s) of hardware acceleration are active.
 * `rffmpeg` does not know what media file(s) is is handling or where it's outputting files to, and cannot alter these paths.

Thus it is imperative that you set up your entire system correctly for `rffmpeg` to work using a "least-common-denominator" approach as required. Please see the [SETUP guide](SETUP.md) for more information.

### Can `rffmpeg` do Wake-On-LAN or other similar options to turn on a transcode server?

Explicitly *no*, though the linuxserver.io [docker mod](https://github.com/linuxserver/docker-mods/tree/jellyfin-rffmpeg) does support this.

I've thought about implementing this more than once (most recently, in response to [Issue #21](https://github.com/joshuaboniface/rffmpeg/issues/21)) but ultimately I do not believe this is worth the complexity and delays it would introduce when spawning processes. That issue does provide one example of a workaround wrapper script that could accomplish this, but I do not plan for it to be a part of `rffmpeg` itself.

### I'm getting an error, help!

First, run though the setup guide again and make sure that everything is set up correctly.

If the problem persists, please check the [closed issues](https://github.com/joshuaboniface/rffmpeg/issues?q=is%3Aissue+sort%3Aupdated-desc+is%3Aclosed) and see if it's been reported before (if it's regarding Emby and you get an "error 127", see [Issue #10](https://github.com/joshuaboniface/rffmpeg/issues/10)).

If it hasn't, you can [ask in our chat](https://matrix.to/#/#rffmpeg:matrix.org) or open a new issue. Ensure you:

1. Enable debug logging in `rffmpeg.yml` (`logging` -> `debug` to `true`) and re-run any failing or incorrect command(s) to obtain debug-level logs for analysis.

1. For issues, use a descriptive and useful title that quickly explains the problem.

1. Clearly explain (in the body of the issue or in your chat message) your setup, what is going wrong, and what you expect should be happening. Don't fret if English isn't your first language or anything like that, as long as you are trying to be clear that's what counts!

1. Include your `rffmpeg.log` and Jellyfin/Emby transcode logs as these are absolutely critical in determining what is going on. Use triple-backticks ("```") to enclose logs inline, both in chat and in issues.

I will probably ask clarifying questions as required; please be prepared to run test commands, etc. as requested and paste the output.

### I found a bug/flaw and fixed it, or made a feature improvement; can I share it?

Absolutely - I'm happy to take pull requests for just about any bugfix or improvement. There is one exception: please refer to the "Can `rffmpeg` mangle/alter FFMPEG arguments?" entry above; unless it's really good work with a very explicitly defined limitation, I probably don't want to go down that route, but I'm more than willing to look at what you've done and consider it on its merits.

### Can you help me set up my server?

I'm always happy to help, though please ensure you try to follow the setup guide first - that's why I wrote it! Support can be found [on Matrix](https://matrix.to/#/#rffmpeg:matrix.org) or via email at `joshua@boniface.me`. Please note though that I may be unresponsive sometimes, though I will get back to you eventually I promise! Please don't open Issues here about setup problems; the Issue tracker is for bugs or feature requests instead.

### `rffmpeg-go` - forked project

There's also a [fork of this script written in Go](https://github.com/aleksasiriski/rffmpeg-go) with semver tags and binaries available, as well as docker images for both the [script](https://github.com/aleksasiriski/rffmpeg-go/pkgs/container/rffmpeg-go) and [Jellyfin](https://github.com/aleksasiriski/jellyfin-rffmpeg).
