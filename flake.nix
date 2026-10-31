{
  # tjor as a nix package (#25): the second package manager after Homebrew.
  # The package installs the tree under libexec and wraps bin/tjor with the
  # host tools the launcher needs (bash >= 4.4, python3 >= 3.11, git, openssl);
  # Docker with compose v2 stays a host requirement, found on PATH at run time,
  # exactly as with the Homebrew formula. A store copy carries no .git and no
  # .tjor-source-sha marker, so it is an INSTALLED RELEASE to the launcher
  # (image-distribution spec, ADR 0008): it pulls the prebuilt images for its
  # VERSION instead of building them, and that holds for `nix run .` from a
  # checkout too — to build images from source, run ./bin/tjor from the
  # checkout. nixpkgs is pinned by flake.lock; `nix flake update` moves it.
  description = "Run AI coding agents inside a portable, fail-closed container cage";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.05";

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
          # image. The wrapper's PATH gives the launcher itself the pinned bash.
          dontPatchShebangs = true;
          installPhase = ''
            runHook preInstall
            mkdir -p "$out/libexec/tjor" "$out/bin"
            cp -R . "$out/libexec/tjor"
            # The wrapper runs the pinned bash with the real script as its
            # argument: the script's shebang stays as written (it is not
            # consulted, so the check below works inside nix's build sandbox,
            # which has no /usr/bin/env), and the launcher still resolves its
            # own tree (TJOR_ROOT) from the script's physical path under libexec.
            makeWrapper "${pkgs.bash}/bin/bash" "$out/bin/tjor" \
              --add-flags "$out/libexec/tjor/bin/tjor" \
              --prefix PATH : ${pkgs.lib.makeBinPath [ pkgs.bash pkgs.python3 pkgs.git pkgs.openssl ]}
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
      # test block runs); the build sandbox has no Docker and no network, which
      # `tjor help` must not need.
      checks = forAll (pkgs: {
        help = pkgs.runCommand "tjor-help" { } ''
          "${self.packages.${pkgs.system}.tjor}/bin/tjor" help | grep -q "fail-closed container cage"
          touch "$out"
        '';
      });
    };
}
