{ ... }:
{
  perSystem =
    {
      pkgs,
      pythonSet,
      workspace,
      ...
    }:
    let
      env = pythonSet.mkVirtualEnv "pkgmap-env" workspace.deps.default;
    in
    rec {
      packages.pkgmap = env;
      packages.default = packages.pkgmap;

      packages.lib = pythonSet."pkgmap-py";
      packages.pkgmap-lib = packages.lib;

      apps.pkgmap = {
        type = "app";
        program = pkgs.lib.getExe' packages.pkgmap "pkgmap";
      };
      apps.default = apps.pkgmap;

      apps.pipeline = {
        type = "app";
        program = pkgs.lib.getExe' packages.pkgmap "pkgmap-pipeline";
      };
      apps.pkgmap-pipeline = apps.pipeline;
    };
}
