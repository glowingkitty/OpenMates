"""Composed videos of videos.generate: an author model writes a Remotion composition rendered on E2B.

Entry points: ``author.compose_video`` (author loop with corrections),
``source.render_source_directly`` (render an existing composition, no author)
and ``source.build_clip_join_source`` (deterministic composition joining mp4
clips). Data shapes live in ``models``; the module contract in ``contract``.
"""
