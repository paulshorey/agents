# Source from a shell or agent launcher when needed. No credentials are loaded.
case ":$PATH:" in
  *":$HOME/.agents/bin:"*) ;;
  *) export PATH="$HOME/.agents/bin:$PATH" ;;
esac
