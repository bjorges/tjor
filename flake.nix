{
  # tjor as a nix package (#25): the second package manager after Homebrew.
  # The package installs the tree under libexec and wraps bin/tjor so that the
  # pinned bash runs it and the tools the launcher's own logic relies on come
  # first on PATH (python3 >= 3.11, git, openssl, and the coreutils, findutils,
  # grep, sed, awk, diff and tar it calls); Docker with compose v2, and the
  # optional ps/column/fzf, stay host tools found behind them on PATH, exactly
  # as with the Homebrew formula. A store copy carries no .git and no
  # .tjor-source-sha marker, so it is an INSTALLED RELEASE to the launcher
  # (image-distribution spec, ADR 0008): it pulls the prebuilt images for its
  # VERSION instead of building them, and that holds for `nix run .` from a
  # checkout too — to build images from source, run ./bin/tjor from the
  # checkout. Pins (charter L11, L23): nixpkgs is a release branch, locked to
  # a commit and narHash by flake.lock (Renovate moves the lock; the branch is
  # bumped by hand at each NixOS release, see CONTRIBUTING "Dependencies").
  # CI builds and checks x86_64-linux only; the other three systems are
  # declared and evaluated, and are built by whoever installs there.
  description = "Run AI coding agents inside a portable, fail-closed container cage";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
      forAll = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
      version = nixpkgs.lib.removeSuffix "\n" (builtins.readFile ./VERSION);
    in {
      packages = forAll (pkgs: {
        tjor = pkgs.stdenvNoCC.mkDerivation {
          pname = "tjor";
          inherit version;
          src = self;
          nativeBuildInputs = [ pkgs.makeWrapper ];
          dontConfigure = true;
          dontBuild = true;
          # Keep every `#!/usr/bin/env bash` as written: the tree holds the
          # entrypoint scripts tjor copies into the container images it builds
          # locally, and a store path in their shebang would break them in the
          # image. The launcher itself runs under the pinned bash because the
          # wrapper execs that bash by store path; checks.help proves it in the
          # build sandbox, which has no /usr/bin/env at all.
          dontPatchShebangs = true;
          installPhase = ''
            runHook preInstall
            mkdir -p "$out/libexec/tjor" "$out/bin"
            cp -R . "$out/libexec/tjor"
            # The wrapper runs the pinned bash with the real script as its
            # argument (the shebang is not consulted), and the launcher still
            # resolves its own tree (TJOR_ROOT) from the script's physical path
            # under libexec. PATH is a prefix: the pinned tools come first, the
            # host's docker and the rest stay reachable behind them.
            makeWrapper "${pkgs.bash}/bin/bash" "$out/bin/tjor" \
              --add-flags "$out/libexec/tjor/bin/tjor" \
              --prefix PATH : ${pkgs.lib.makeBinPath [
                pkgs.bash pkgs.python3 pkgs.git pkgs.openssl
                pkgs.coreutils pkgs.findutils pkgs.gnugrep pkgs.gnused pkgs.gawk pkgs.diffutils pkgs.gnutar
              ]}
            runHook postInstall
          '';
          meta = {
            description = "Run AI coding agents inside a portable, fail-closed container cage";
            homepage = "https://github.com/bjorges/tjor";
            license = pkgs.lib.licenses.mit;
            mainProgram = "tjor";
            platforms = systems;
          };
        };
        default = self.packages.${pkgs.system}.tjor;
      });

      apps = forAll (pkgs: {
        default = {
          type = "app";
          program = "${self.packages.${pkgs.system}.tjor}/bin/tjor";
        };
      });

      # `nix flake check`: the wrapped launcher starts under the pinned bash
      # and python and prints its usage (the same proof the Homebrew formula's
      # test block runs); the build sandbox has no Docker, no network and no
      # /usr/bin/env, none of which `tjor help` may need.
      checks = forAll (pkgs: {
        help = pkgs.runCommand "tjor-help" { } ''
          "${self.packages.${pkgs.system}.tjor}/bin/tjor" help | grep -q "fail-closed container cage"
          touch "$out"
        '';
      });
    };
}
