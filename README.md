# rffmpeg

`rffmpeg` is a remote FFmpeg wrapper used to execute FFmpeg commands on a remote server via SSH. It is most useful in situations involving media servers such as Jellyfin (our reference user), where one might want to perform transcoding actions with FFmpeg on a remote machine or set of machines which can better handle transcoding, take advantage of hardware acceleration, or distribute transcodes across multiple servers for load balancing.

## Quick usage

1. Install the required Python 3 dependencies `yaml` and `subprocess` (`sudo apt install python3-yaml python3-subprocess` in Debian).

1. Create the directory `/etc/rffmpeg`.

1. Copy the `rffmpeg.yml.sample` file to `/etc/rffmpeg/rffmpeg.yml` and edit it to suit your needs.

1. Install `rffmpeg.py` somewhere useful, for instance at `/usr/local/bin/rffmpeg.py`.

1. Create symlinks for the command names `ffmpeg` and `ffprobe` to `rffmpeg.py`, for example `sudo ln -s /usr/local/bin/rffmpeg.py /usr/local/bin/ffmpeg` and `sudo ln -s /usr/local/bin/rffmpeg.py /usr/local/bin/ffprobe`.

1. Set your media program to use `rffmpeg.py` via the symlink names created above, instead of any other `ffmpeg` binary.

1. Profit!

For more detailed instructions, including what must be done to ensure data can be passed between the servers, please see [the SETUP guide](SETUP.md).

## rffmpeg options and caveats

The `rffmpeg.yml.sample` is self-documented for the most part. Some additional important information you might need is presented below.

### Remote hosts

rffmpeg supports setting multiple hosts. It keeps state in `/run/shm/rffmpeg` of all running processes, and these state files are used during rffmpeg's initialization in order to determine the optimal target host. rffmpeg will run through these hosts sequentially, choosing the one with the fewest running rffmpeg jobs. This helps distribute the transcoding load across multiple servers, and can also provide redundancy if one of the servers is offline - rffmpeg will detect if a host is unreachable and set it "bad" for the remainder of the run, thus skipping it until the process completes.

Hosts can also be assigned weights (see `rffmpeg.yml.sample` for an example) that allow the host to take on that many times the number of active processes versus weight-1 hosts. The `rffmpeg` process does a floor division of the number of active processes on a host with that host weight to determine its "weighted [process] count", which is then used instead to determine the lease-loaded host to use. Note that `rffmpeg` does not take into account actual system load, etc. when determining which host to use; it treats each running command equally regardless of how intensive it actually is.

#### Host lists

Hosts are specified as a YAML list in the relevant section of `rffmpeg.yml`, with one list entry per target. A single list entry can be specfied in one of two ways. Either a direct list value of the hostame/IP:

```
- myhostname.domain.tld
```

Or as a fully expanded `name:`/`weight:` pair.

```
- name: myhostname.domain.tld
  weight: 2
```

The first, direct list value formatting implies `weight: 1`. Examples of both styles can be found in the same configuration.

You can get creative with this list, especially since `rffmpeg` always checks the list in order to find the next available host. For an example of a complex setup, if you had 3 hosts, and wanted 1+2+2 processes, the following would be the default way to acheive this:

```
- name: host1
  weight: 1
- name: host2
  weight: 2
- name: host3
  weight: 2
```

This would however spread processes out like this, which might work well, but might not for some usecases:

```
proc1: host1
proc2: host2
proc3: host2
proc4: host3
proc5: host3
proc6: host1
etc.
```

You could instead specify the hosts like this:

```
- host1
- host2
- host3
- host2
- host3
```

Which would instead give a process spread like:

```
proc1: host1
proc2: host2
proc3: host3
proc4: host2
proc5: host3
proc6: host1
etc.
```

Experiment with the ordering based on your load and usecase.

#### Localhost and fallback

If one of the hosts in the config file is called "localhost", rffmpeg will run locally without SSH. This can be useful if the local machine is also a powerful transcoding device.

In addition, rffmpeg will fall back to "localhost" should it be unable to find any working remote hosts. This helps prevent situations where rffmpeg cannot be run due to none of the remote host(s) being available.

In both cases, note that, if hardware acceleraton is configured, it *must* be available on the local host as well, or the `ffmpeg` commands will fail. There is no easy way around this without rewriting flags, and this is currently out-of-scope for `rffmpeg`. You should always use a lowest-common-denominator approach when deciding on what additional option(s) to enable, such that any configured host can run any process.

The exact path to the local `ffmpeg` and `ffprobe` binaries can be overridden in the configuration, should their paths not match those of the remote system(s). If these options are not specified, the remote paths are used.

### Terminating rffmpeg

When running rffmpeg manually, *do not* exit it with `Ctrl+C`. Doing so will likely leave the `ffmpeg` process running on the remote machine. Instead, enter `q` and a newline ("Enter") into the rffmpeg process, and this will terminate the entire command cleanly. This is the method that Jellyfin uses to communicate the termination of an `ffmpeg` process.

## FAQ

### Why did you make rffmpeg?

My virtualization setup (multiple 1U nodes with lots of live migration/failover) didn't lend itself well to passing a GPU into my Jellyfin VM, but I wanted to offload transcoding because doing 4K HEVC transcodes with a CPU performs horribly. I happened to have another machine (my "base" remote headless desktop/gaming server) which had a GPU, so I wanted to find a way to offload the transcoding to it. I came up with `rffmpeg` as a simple wrapper to the `ffmpeg` and `ffprobe` calls that Jellyfin (and Emby, and likely other media servers too) makes which would run them on that host instead. After finding it quite useful myself, I released it publicly as GPLv3 software so that others may benefit as well!

### What supports `rffmpeg`?

This depends on what "layer" you're asking at.

* Media Servers: Jellyfin is officially supported; Emby seems to work fine, with caveats (see [Issue #10](https://github.com/joshuaboniface/rffmpeg/issues/10)); no others have been tested to my knowledge
* Operating Systems (source): Debian and its derivatives (Ubuntu, Linux Mint, etc.) should all work perfectly; other Linux operating systems should work fine too as the principles are the same; MacOS should work since it has an SSH client built in; Windows might work if it has an SSH client installed
* Operating Systems (target): Any Linux system which [`jellyfin-ffmpeg`](https://github.com/jellyfin/jellyfin-ffmpeg) supports, which is currently just Debian and Ubuntu; Windows *might* work if you can get an SSH server running on it (see [Issue #17](https://github.com/joshuaboniface/rffmpeg/issues/17))
* Install Methods for Jellyfin: Native packages/installers/archives are recommended; Docker containers can be made to work by exporting the `/config` path (see [the setup guide](SETUP.md)) but this is slightly more difficult and is not explicitly covered in the guide
* Install Methods for `rffmpeg`: Direct installation is recommended; a [Docker container to act as an ffmpeg transcode target](https://github.com/BasixKOR/rffmpeg-docker) has been created by @BasixKOR

### Can `rffmpeg` mangle/alter FFMPEG arguments?

Explicitly *no*. `rffmpeg` is not designed to interact with the arguments that the media server passes to `ffmpeg`/`ffprobe` at all, nor will it. This is an explicit design decision due to the massive complexity of FFMpeg - to do this, I would need to create a mapping of just about every possible FFMpeg argument, what it means, and when to turn it on or off, which is way out of scope.

This has a number of side effects:

 * `rffmpeg` does not know whether hardware acceleration is turned on or not (see above caveats about localhost and fallback)
 * `rffmpeg` does not know what media is playing or where it's outputting files to, and cannot alter these paths
 * `rffmpeg` cannot turn on or off special `ffmpeg` options depending on the host selected

### Can `rffmpeg` do Wake-On-LAN or other similar options to turn on a transcode server?

Right now, no. I've thought about implementing this more than once (most recently, in response to [Issue #21](https://github.com/joshuaboniface/rffmpeg/issues/21)) but ultimately I've never though this was worth the complexity and delays in spwaning that it would add to the tool. That issue does provide one example of a workaround wrapper script that could accomplish this, but I don't see it being a part of the actual tool itself.

### I'm getting an error, help!

First, run though the setup guide again and make sure that everything is set up correctly.

If the problem persists, please check the [closed issues](https://github.com/joshuaboniface/rffmpeg/issues?q=is%3Aissue+sort%3Aupdated-desc+is%3Aclosed) and see if it's been reported before (if it's regarding Emby and you get an "error 127", see [Issue #10](https://github.com/joshuaboniface/rffmpeg/issues/10)).

If it hasn't, please open a new issue. Ensure you:

1. Use a descriptive and useful title that quickly explains the problem.

1. Clearly explain in the body of the issue your setup, what is going wrong, and what you expect should be happening. Don't fret if English isn't your first language or anything like that, as long as you are trying to be clear that's what counts!

1. Include your `rffmpeg.log` and Jellyfin/Emby `ffmpeg-transcode-*.txt` logs.

I will probably ask clarifying questions as required; please be prepared to run test commands, etc. as requested and paste the output.

### I found a bug/flaw and fixed or, or made a feature improvement; can I share it?

Absolutely - I'm happy to take pull requests. Though please refer to the "Can `rffmpeg` mangle/alter FFMPEG arguments?" entry above; unless it's really good work with a very explicitly defined limitation, I probably don't want to go down that route, but I'm more than willing to look at what you've done and consider it on its merits.

### Can you help me set up my server?

I'm always happy to help, though please ensure you try to follow the setup guide first. I can be found [on Matrix](https://matrix.to/#/@joshuaboniface:bonifacelabs.ca) or via email at `joshua@boniface.me`. Please note though that I may be unresponsive sometimes, though I will get back to you eventually I promise! Please don't open Issues here about setup problems; the Issue tracker is for bugs or feature requests instead.
