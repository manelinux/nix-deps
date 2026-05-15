{ pkgs ? import <nixpkgs> {} }:

pkgs.python3Packages.buildPythonApplication {
  pname = "nix-deps";
  version = "1.9.0";

  src = ./.;

  format = "other";

  installPhase = ''
    mkdir -p $out/bin
    cp nix-deps.py $out/bin/nix-deps
    chmod +x $out/bin/nix-deps
  '';

  meta = with pkgs.lib; {
    description = "See the real cost of installing packages on NixOS";
    homepage = "https://github.com/manelinux/nix-deps";
    license = licenses.mit;
    platforms = platforms.linux;
    maintainers = [ ];
  };
}
