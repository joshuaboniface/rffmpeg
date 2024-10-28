# Example Setup Guide

This example setup is the one I use for `rffmpeg` with Jellyfin. It uses 2 servers: a media server running Jellyfin called `jellyfin1`, and a remote transcode server called `transcode1`. Both systems run Debian GNU/Linux, though the commands below should also work on Ubuntu. Throughout this guide I assume you are running as an unprivileged user with `sudo` privileges (i.e. in the group `sudo`). Basic knowledge of Linux CLI usage is assumed. Whenever a verbatim command is specified, it will be prefixed by the relevant host to run it on (either `jellyfin1` or `transcode1`) and then a `$` prompt indicator. Any command output is usually not shown unless it is relevant.

This guide is provided as a basic starting point - there are myriad possible combinations of systems, and I try to keep `rffmpeg` quite flexible. Feel free to experiment.

## Set up the media server (`jellyfin1`)

### Basic Setup

1. Install Jellyfin (or similar FFMPEG-using media server) on your machine. This guide assumes you're using native `.deb` packages.

1. Make note of the Jellyfin service user's details, specifically the UID and any groups (and GIDs) it is a member of; this will be needed later on.

   ```
   jellyfin1 $ id jellyfin
   uid=110(jellyfin) gid=117(jellyfin) groups=117(jellyfin)
   ```

1. Make note of the Jellyfin data path; this will be needed later on. By default when using native OS packages, this is `/var/lib/jellyfin`. If you choose to move this directory, do so now (I personally use `/srv/jellyfin` but this guide will assume the default).

   To make life easier below, you can store this in a variable that I will reference frequently later:

   ```
   jellyfin1 $ export jellyfin_data_path="/var/lib/jellyfin"
   jellyfin1 $ export jellyfin_cache_path="/var/lib/jellyfin"
   transcode1 $ export jellyfin_data_path="/var/lib/jellyfin"
   transcode1 $ export jellyfin_cache_path="/var/lib/jellyfin"
   ```

   The important subdirectories for `rffmpeg`'s operation are:

   * `$jellyfin_cache_path/`: Used to store cached extracted data.
   * `$jellyfin_cache_path/transcodes/`: Used to store on-the-fly transcoding files, and configurable separately in Jellyfin but with `rffmpeg` I recommend leaving it at the default location under the cache path.
   * `$jellyfin_data_path/data/subtitles/`: Used to store on-the-fly extracted subtitles so that they can be reused later.
   * `$jellyfin_data_path/.ssh/`: This doesn't exist yet but will after the next step.

   **NOTE:** On Docker, these directories are different. The main data directory (our `jellyfin_data_path`) is `/config`, and the cache directory is separate at `/cache`. Both must be exported and mounted on targets for proper operation.

   **NOTE:** On Jellyfin 10.10.x and newer, temporary transient files were moved into the system temporary storage path (on Linux, usually `/tmp`). This will break rffmpeg for certain tasks that use these files, for instance trickplay generation. To restore the previous behaviour, ensure you set the `TMPDIR` environment variable for your Jellyfin service to a path under the data path above, for example `/var/lib/jellyfin/temp`, and create this directory with correct ownership and permissions.

1. Create an SSH keypair to use for `rffmpeg`'s login to the remote server. For ease of use with the following steps, use the Jellyfin service user (`jellyfin`) to create the keypair and store it under its home directory (the Jellyfin data path above). I use `rsa` here but you can substitute `ed25519` instead (avoid `dsa` and `ecdsa` for reasons I won't get into here). Once done, copy the public key to `authorized_keys` which will be used to authenticate the key later.

   ```
   jellyfin1 $ sudo -u jellyfin mkdir ${jellyfin_data_path}/.ssh
   jellyfin1 $ sudo chmod 700 ${jellyfin_data_path}/.ssh
   jellyfin1 $ export keytype="rsa"
   jellyfin1 $ sudo -u jellyfin ssh-keygen -t ${keytype} -f ${jellyfin_data_path}/.ssh/id_${keytype}
   jellyfin1 $ sudo -u jellyfin cp -a ${jellyfin_data_path}/.ssh/id_${keytype}.pub ${jellyfin_data_path}/.ssh/authorized_keys
   ```

   It is important that you do not alter the permissions under this `.ssh` directory or this can cause SSH to fail later. The SSH *must* occur as the `jellyfin` user for this to work.

1. Scan and save the SSH host key of the transcode server(s), to avoid a prompt later:

   ```
   jellyfin1 $ ssh-keyscan transcode1 | sudo -u jellyfin tee -a ${jellyfin_data_path}/.ssh/known_hosts
   ```

   * **NOTE:** Ensure you use the exact name here that you will use in `rffmpeg`. If this is an FQDN (e.g. `jellyfin1.mydomain.tld`) or an IP (e.g. `192.168.0.101`) instead of a short name, use that instead in this command, or repeat it for every possible option (it doesn't hurt).

### `rffmpeg` Setup

1. Install the required Python3 dependencies of `rffmpeg`:

   ```
   jellyfin1 $ sudo apt -y install python3-yaml
   jellyfin1 $ sudo apt -y install python3-click
   jellyfin1 $ sudo apt -y install python3-subprocess
   ```

   * **NOTE:** On some Ubuntu versions, `python3-subprocess` does not exist, and should instead be part of the Python standard library. Skip installing this package if it can't be found.

1. Clone the `rffmpeg` repository somewhere onto the system, then install the `rffmpeg` binary, make it executable, and prepare symlinks for the command names `ffmpeg` and `ffprobe` to it. I recommend storing these in `/usr/local/bin` for simplicity and so that they are present on the default `$PATH` for most users.

   ```
   jellyfin1 $ git clone https://github.com/joshuaboniface/rffmpeg  # or download the files manually
   jellyfin1 $ sudo cp rffmpeg/rffmpeg /usr/local/bin/rffmpeg
   jellyfin1 $ sudo chmod +x /usr/local/bin/rffmpeg
   jellyfin1 $ sudo ln -s /usr/local/bin/rffmpeg /usr/local/bin/ffmpeg
   jellyfin1 $ sudo ln -s /usr/local/bin/rffmpeg /usr/local/bin/ffprobe
   ```

1. Optional: Create a directory for the `rffmpeg` configuration at `/etc/rffmpeg`, then copy `rffmpeg.yml.sample` to `/etc/rffmpeg/rffmpeg.yml` and edit it to suit your needs if required. Generally, if you're following this guide exactly, you will not need to install this file or adjust anything in in it. If you do require help though, I require debug logging to be enabled via the configuration file, so it's probably best to get this out of the way when installing `rffmpeg`:

   ```
   jellyfin1 $ sudo mkdir -p /etc/rffmpeg
   jellyfin1 $ sudo cp rffmpeg/rffmpeg.yml.sample /etc/rffmpeg/rffmpeg.yml
   jellyfin1 $ sudo $EDITOR /etc/rffmpeg/rffmpeg.yml  # if required
   ```

1. Initialize `rffmpeg` (note the `sudo` command) and add at the target host to it. You can add other hosts now or later, and set weights of hosts, if required; for full details see the [main README](README.md) or run `rffmpeg --help` to view the CLI help menu.

   ```
   jellyfin1 $ sudo rffmpeg init --yes
   jellyfin1 $ rffmpeg add --weight 1 transcode1
   ```

### NFS Setup

* **WARNING:** This guide assumes your hosts are on the same private local network. It is not recommended to run NFS over the Internet as it is unencrypted, and any rffmpeg connection will be very bandwidth-intensive. If you must have both systems in separate networks, consider other remote filesystems like SSHFS in such cases as these will offer greater privacy and robustness.

1. Install the NFS kernel server. We will use NFS to export the various required directories so the transcode machine can read from and write to them.

   ```
   jellyfin1 $ sudo apt -y install nfs-kernel-server
   ```

1. Create an `/etc/exports` configuration. What to put here can vary a lot, but here are some important points:

   * Always export the `${jellyfin_data_path}` in full. Advanced users might be able to export the required subdirectories individually, but I find this to be not worth the hassle.
   * Note the security options of NFS. It will limit mounts to the IP addresses specified. If your home network is secure, you can use the entire network, e.g. `192.168.0.0/24`, but I would recommend determining the exact IP of your transcode server(s) and use them explicitly, e.g. for this example `192.168.0.101` and `192.168.0.102`.
   * If your `transcodes` directory is not on a **native Linux filesystem** (i.e. external to Jellyfin, such as on a NAS exported by NFS, SMB, etc.), then you may experience delays of ~15-60s when playback starts. This is because NFS uses a file attribute cache that in most applications greatly increases performance, however for this usecase it causes a delay in Jellyfin seeing the `.ts` files. The solution for this is to reduce the NFS cache time by adding `sync` and `actimeo=1` to your NFS mount(s) (command or fstab), which will set the NFS file attribute cache to 1 second (reducing the NFS delay to ~1-2 seconds). This time can be further reduced to 0 by setting the `noac` option, but this is not normally recommended because it will negatively impact the performance other NFS applications. Verify that your mount added the `actimeo=1` parameter correctly by checking `mount` or `cat /proc/mounts`, which will show `sync,acregmin=1,acregmax=1,acdirmin=1,acdirmax=1` as parameters for your `transcodes` mount. 
   * If your media is local to the Jellyfin server (and not already mountable on the transcode host(s) via a remote filesystems like NFS, Samba, CephFS, etc.), also add an export for it as well.

   An example `/etc/exports` file would look like this:

   ```
   # /etc/exports: the access control list for filesystems which may be exported
   #               to NFS clients.  See exports(5).
   #
   # Other examples removed

   # jellyfin_data_path   first host                                                  second host, etc.
   /var/lib/jellyfin      192.168.0.101/32(rw,sync,no_subtree_check,no_root_squash)   192.168.0.102/32(rw,sync,no_subtree_check,no_root_squash)
   # jellyfin_cache_path  first host                                                  second host, etc.
   /var/cache/jellyfin    192.168.0.101/32(rw,sync,no_subtree_check,no_root_squash)   192.168.0.102/32(rw,sync,no_subtree_check,no_root_squash)
   # Local media path if required
   /srv/mymedia           192.168.0.101/32(rw,sync,no_subtree_check,no_root_squash)   192.168.0.102/32(rw,sync,no_subtree_check,no_root_squash)
   ```

1. Reload the exports file and ensure the NFS server is properly exporting it now:

   ```
   jellyfin1 $ sudo exportfs -arfv
   jellyfin1 $ sudo exportfs
   /var/lib/jellyfin   192.168.0.101/32
   /var/lib/jellyfin   192.168.0.102/32
   /var/cache/jellyfin 192.168.0.101/32
   /var/cache/jellyfin 192.168.0.102/32
   ```

## Set up the transcode server (`transcode1`)

1. Install and configure anything you need for hardware transcoding, if applicable. For example GPU drivers if using a GPU for transcoding.

   * **NOTE:** Make sure you understand the caveats of using hardware transcoding with `rffmpeg` from [the main README](README.md#hardware-acceleration).

1. Install the correct `jellyfin-ffmpeg` package for your version of Jellyfin; check which version is installed on your `jellyfin1` system with `dpkg -l | grep jellyfin-ffmpeg`, then install that version on this host too; follow the same steps as you would to install Jellyfin on the media server, only don't install `jellyfin` (and `jellyfin-server`/`jellyfin-web`) itself, just the `jellyfin-ffmpeg` of the required version.

   ```
   jellyfin1  $ dpkg -l | grep jellyfin-ffmpeg
   ii  jellyfin-ffmpeg6                     6.0.1-8-bookworm                        amd64        Tools for transcoding, streaming and playing of multimedia files
   transcode1 $ sudo apt -y install curl gnupg
   transcode1 $ curl -fsSL https://repo.jellyfin.org/ubuntu/jellyfin_team.gpg.key | sudo gpg --dearmor -o /etc/apt/trusted.gpg.d/jellyfin.gpg
   transcode1 $ echo "deb [arch=$( dpkg --print-architecture )] https://repo.jellyfin.org/$( awk -F'=' '/^ID=/{ print $NF }' /etc/os-release ) $( awk -F'=' '/^VERSION_CODENAME=/{ print $NF }' /etc/os-release ) main" | sudo tee /etc/apt/sources.list.d/jellyfin.list
   transcode1 $ sudo apt update
   transcode1 $ sudo apt install jellyfin-ffmpeg6
   ```

1. Install the NFS client utilities:

   ```
   transcode1 $ sudo apt install -y nfs-common
   ```

1. Create the Jellyfin service user and its default group; ensure you use the exact same UID and GID values you found in the beginning of the last section and adjust the example here to match yours:

   ```
   transcode1 $ sudo groupadd --gid 117 jellyfin
   transcode1 $ sudo useradd --uid 110 --gid jellyfin --shell /bin/bash --no-create-home --home-dir ${jellyfin_data_path} jellyfin
   ```

   * **NOTE:** For some hardware acceleration, you might need to add this user to additional groups. For example `--groups video,render`.

   * **NOTE:** The UID and GIDs here are dynamic; on the `jellyfin1` machine, they would have been selected automatically at install time with the next available ID in the range 100-199 (at least in Debian/Ubuntu). However, this means that the exact UID of your Jellyfin service user might not be available on your transcode server, depending on what packages are installed and in what order. If there is a conflict, you must adjust user IDs on one side or the other so that they match on both machines. You can use `sudo usermod` to change a user's ID if required.

1. Create the Jellyfin data directory at the same location as on the media server, and set it immutable so that it won't be written to if the NFS mount goes down:

   ```
   transcode1 $ sudo mkdir ${jellyfin_data_path}
   transcode1 $ sudo chattr +i ${jellyfin_data_path}
   ```

   * **NOTE:** Don't worry about permissions here; the mount will set those.

1. Create the NFS client mount. There are two main ways to do this:

   * Use the traditional `/etc/fstab` by adding a new entry like so, replacing the paths and hostname as required, and then mounting it:

      ```
      transcode1 $ echo "jellyfin1:${jellyfin_data_path} ${jellyfin_data_path} nfs defaults,vers=3,sync" | sudo tee -a /etc/fstab
      transcode1 $ echo "jellyfin1:${jellyfin_cache_path} ${jellyfin_cache_path} nfs defaults,vers=3,sync" | sudo tee -a /etc/fstab
      transcode1 $ sudo mount ${jellyfin_data_path}
      transcode1 $ sudo mount ${jellyfin_cache_path}
      ```

   * Use a SystemD `mount` unit, which is a newer way of doing mounts with SystemD. I personally prefer this method as I find it easier to set up automatically, but this is up to preference. An example based on mine would be:

      ```
      transcode1 $ cat /etc/systemd/system/var-lib-jellyfin.mount
      [Unit]
      Description = NFS volume for Jellyfin data directory
      Requires = network-online.target
      After = network-online.target

      [Mount]
      type = nfs
      What = jellyfin1:/var/lib/jellyfin
      Where = /var/lib/jellyfin
      Options = _netdev,sync,vers=3

      [Install]
      WantedBy = remote-fs.target
      ```

      ```
      transcode1 $ cat /etc/systemd/system/var-cache-jellyfin.mount
      [Unit]
      Description = NFS volume for Jellyfin cache directory
      Requires = network-online.target
      After = network-online.target

      [Mount]
      type = nfs
      What = jellyfin1:/var/cache/jellyfin
      Where = /var/cache/jellyfin
      Options = _netdev,sync,vers=3

      [Install]
      WantedBy = remote-fs.target
      ```

      Once the unit file is created, you can then reload the unit list and mount it:

      ```
      transcode1 $ sudo systemctl daemon-reload
      transcode1 $ sudo systemctl enable --now var-lib-jellyfin.mount
      transcode1 $ sudo systemctl enable --now var-cache-jellyfin.mount
      ```

      Note that mount units are fairly "new" and can be a bit finicky, be sure to read the SystemD documentation if you get stuck! Generally for new users, I'd recommend the `/etc/fstab` method instead.

    **NOTE:** Don't forget about `actimeo=1` here if you need it!

1. Mount your media directories in the **same location(s)** as on the media server. If you exported them via NFS from your media server, use the process above only for those directories instead.

## Test the setup

1. On the media server, verify that SSH as the Jellyfin service user is working as expected to each transcoding server:

   ```
   jellyfin1 $ sudo -u jellyfin ssh -i ${jellyfin_data_path}/.ssh/id_rsa jellyfin@transcode1 uname -a
   Linux transcode1 [...]
   ```

1. Validate that `rffmpeg` itself is working by calling its `ffmpeg` and `ffprobe` aliases with the `-version` option:

   ```
   jellyfin1 $ sudo -u jellyfin /usr/local/bin/ffmpeg -version
   ffmpeg version 5.0.1-Jellyfin Copyright (c) 2000-2022 the FFmpeg developers
   built with gcc 10 (Debian 10.2.1-6)
   [...]
   jellyfin1 $ sudo -u jellyfin /usr/local/bin/ffprobe -version
   ffprobe version 5.0.1-Jellyfin Copyright (c) 2007-2022 the FFmpeg developers
   built with gcc 10 (Debian 10.2.1-6)
   [...]
   ```

As long as these steps work, all further steps should as well. If one of these *doesn't* work, double-check all previous steps and confirm that everything is set up right.

## Configure Jellyfin to use `rffmpeg`

**NOTE**: With Jellyfin 10.8.13 and newer, the ability to configure the `ffmpeg` path has been removed from the WebUI due to major security concerns. You must follow this method to change it.

1. On the `jellyfin1` system, edit `/etc/default/jellyfin`:

   ```
   jellyfin1 $ sudo $EDITOR /etc/default/jellyfin
   ```

1. Change the value of `JELLYFIN_FFMPEG_OPT` to be `--ffmpeg=/usr/local/bin/ffmpeg` (the `rffmpeg` alias name `ffmpeg` in whatever path you installed `rffmpeg` to).

1. On Jellyfin 10.10.x or newer, add `TMPDIR=$jellyfin_cache_path/temp`, for instance `TMPDIR=/var/cache/jellyfin/temp`, to ensure this is properly synchronized over the network.

1. Save the file and restart Jellyfin:

   ```
   jellyfin1 $ sudo systemctl restart jellyfin
   ```

If you wish to use hardware transcoding, you must also enable it in Jellyfin's WebUI:

1. Navigate to Hamburger Menu -> Administration -> Dashboard, navigate to Playback.

1. Configure any hardware acceleration you require and have set up on the remote server(s).

1. Save the settings.

Now, run `rffmpeg log -f` on the `jellyfin1` machine and try to play a video that requires transcoding. You should see `rffmpeg` spawn a process on the `jellyfin1` machine, which then begins running the `ffmpeg` process on the `transcode1` machine, writing data to the configured paths, and playback should begin normally. If anything doesn't work, double-check all previous steps and confirm that everything is set up right.

## NOTE for NVEnv/NVDec Hardware Acceleration

If you are using NVEnv/NVDec, you will need to symlink the `.nv` folder inside the Jellyfin user's homedir (i.e. `/var/lib/jellyfin/.nv`) to somewhere outside of the NFS volume on both the Jellyfin and transcoding hosts. For example:

   ```
   jellyfin1  $ sudo mv /var/lib/jellyfin/.nv /var/lib/nvidia-cache  # or "sudo mkdir /var/lib/nvidia-cache" and "sudo chown jellyfin /var/lib/nvidia-cache" if it does not yet exist
   jellyfin1  $ sudo ln -s /var/lib/nvidia-cache /var/lib/jellyfin/.nv
   transcode1 $ sudo mkdir /var/lib/nvidia-cache
   transcode1 $ sudo chown jellyfin /var/lib/nvidia-cache
   transcode1 $ ls -alh /var/lib/jellyfin
   [...]
   lrwxrwxrwx  1 root     root         17 Jun 11 15:51 .nv -> /var/lib/nvidia-cache
   [...]
   ```

Be sure to adjust these paths to match your Jellyfin setup. The name of the target doesn't matter too much, as long as `.nv` inside the homedir is symlinked to it and it is owned by the `jellyfin` service user.

This is because some functions of FFMpeg's NVEnc/NVDec stack - specifically the `scale_cuda` and `tonemap_cuda` filters - leverage this directory to cache their JIT codes, and this can result in very slow startup times and very poor transcoding performance due to NFS locking issues. See https://developer.nvidia.com/blog/cuda-pro-tip-understand-fat-binaries-jit-caching/ for further information.

Alternatively, based on that link, you might also be able to experiment with the environment variables that control the JIT caching to move it somewhere else, but this has not been tested by the author. Feel free to experiment and find the best solution for your setup.
