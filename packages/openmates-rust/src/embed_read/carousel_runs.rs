//! spec: app-skills.answer.only-result-embeds-in-body
//! Carousel grouping of answer-body embed previews, ported from web
//! `assignCarouselRuns` (`bodyEmbedPolicy.ts`). The core has no parsed-body
//! node tree, so the input is one level of body nodes as a shell sees them;
//! a shell applies the function again to the children of each container node
//! (web recurses into every non-paragraph node that has content).

/// What one body node is, as far as carousel grouping cares.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BodyNodeKind {
    /// A paragraph without content (blank line).
    EmptyParagraph,
    /// A paragraph with content.
    Paragraph,
    /// A large embed preview (`[!](embed:ref)` block).
    EmbedLarge,
    /// Any other node (heading, list, code block, quote, ...).
    Other,
}

/// One body node at one nesting level.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BodyNode {
    /// Node kind.
    pub kind: BodyNodeKind,
    /// Embed ref of an `EmbedLarge` node; empty otherwise.
    pub embed_ref: String,
    /// True for a placeholder whose type or children are not known yet: it keeps
    /// its position, renders nothing and is never counted.
    pub hidden: bool,
}

/// Where a kept input node ends up and its carousel metadata.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CarouselPlacement {
    /// Index of the node in the input list.
    pub source_index: usize,
    /// Position in its run; -1 for hidden placeholders and non-embed nodes.
    pub carousel_index: i32,
    /// Visible items in the run; 0 for hidden placeholders and non-embed nodes.
    pub carousel_total: u32,
    /// Ref of the first visible embed of the run; empty when not applicable.
    pub run_ref: String,
}

fn plain(source_index: usize) -> CarouselPlacement {
    CarouselPlacement {
        source_index,
        carousel_index: -1,
        carousel_total: 0,
        run_ref: String::new(),
    }
}

fn flush_run(run: &mut Vec<usize>, nodes: &[BodyNode], out: &mut Vec<CarouselPlacement>) {
    if run.is_empty() {
        return;
    }
    let visible: Vec<usize> = run.iter().copied().filter(|i| !nodes[*i].hidden).collect();
    let run_ref = visible
        .first()
        .map(|i| nodes[*i].embed_ref.clone())
        .unwrap_or_default();
    let mut index = 0i32;
    for &i in run.iter() {
        if nodes[i].hidden {
            out.push(plain(i));
        } else {
            out.push(CarouselPlacement {
                source_index: i,
                carousel_index: index,
                carousel_total: visible.len() as u32,
                run_ref: run_ref.clone(),
            });
            index += 1;
        }
    }
    run.clear();
}

/// Groups consecutive `EmbedLarge` nodes into carousel runs. Empty paragraphs
/// inside a run are dropped; hidden placeholders stay in place but are not
/// counted. Returns the kept nodes in output order (dropped empty paragraphs
/// are absent), each with its carousel metadata.
pub fn assign_carousel_runs(nodes: &[BodyNode]) -> Vec<CarouselPlacement> {
    let mut out = Vec::new();
    let mut run: Vec<usize> = Vec::new();
    let mut pending_empties: Vec<usize> = Vec::new();
    for (i, node) in nodes.iter().enumerate() {
        match node.kind {
            BodyNodeKind::EmbedLarge => {
                pending_empties.clear();
                run.push(i);
            }
            BodyNodeKind::EmptyParagraph if !run.is_empty() => pending_empties.push(i),
            _ => {
                flush_run(&mut run, nodes, &mut out);
                out.extend(pending_empties.drain(..).map(plain));
                out.push(plain(i));
            }
        }
    }
    flush_run(&mut run, nodes, &mut out);
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn embed(r: &str) -> BodyNode {
        BodyNode {
            kind: BodyNodeKind::EmbedLarge,
            embed_ref: r.into(),
            hidden: false,
        }
    }
    fn hidden(r: &str) -> BodyNode {
        BodyNode {
            hidden: true,
            ..embed(r)
        }
    }
    fn node(kind: BodyNodeKind) -> BodyNode {
        BodyNode {
            kind,
            embed_ref: String::new(),
            hidden: false,
        }
    }

    #[test]
    fn consecutive_embeds_form_one_run_and_inner_empties_drop() {
        let nodes = [
            embed("a"),
            node(BodyNodeKind::EmptyParagraph),
            embed("b"),
            embed("c"),
        ];
        let out = assign_carousel_runs(&nodes);
        let idx: Vec<_> = out
            .iter()
            .map(|p| (p.source_index, p.carousel_index, p.carousel_total))
            .collect();
        assert_eq!(idx, vec![(0, 0, 3), (2, 1, 3), (3, 2, 3)]);
        assert!(out.iter().all(|p| p.run_ref == "a"));
    }

    #[test]
    fn text_between_embeds_splits_runs() {
        let nodes = [embed("a"), node(BodyNodeKind::Paragraph), embed("b")];
        let out = assign_carousel_runs(&nodes);
        assert_eq!(out[0].carousel_total, 1);
        assert_eq!(out[1].carousel_index, -1);
        assert_eq!((out[2].carousel_total, out[2].run_ref.as_str()), (1, "b"));
    }

    #[test]
    fn hidden_placeholder_keeps_position_but_is_not_counted() {
        let nodes = [hidden("p"), embed("a"), embed("b")];
        let out = assign_carousel_runs(&nodes);
        assert_eq!(
            (
                out[0].carousel_index,
                out[0].carousel_total,
                out[0].run_ref.as_str()
            ),
            (-1, 0, "")
        );
        assert_eq!((out[1].carousel_index, out[1].carousel_total), (0, 2));
        assert_eq!((out[2].carousel_index, out[2].run_ref.as_str()), (1, "a"));
    }

    #[test]
    fn empty_paragraphs_survive_only_before_next_content() {
        let nodes = [
            embed("a"),
            node(BodyNodeKind::EmptyParagraph),
            node(BodyNodeKind::Other),
            node(BodyNodeKind::EmptyParagraph),
        ];
        let src: Vec<_> = assign_carousel_runs(&nodes)
            .iter()
            .map(|p| p.source_index)
            .collect();
        assert_eq!(src, vec![0, 1, 2, 3]);
        let trailing = [embed("a"), node(BodyNodeKind::EmptyParagraph)];
        assert_eq!(assign_carousel_runs(&trailing).len(), 1);
    }

    #[test]
    fn all_hidden_run_has_empty_run_ref() {
        let out = assign_carousel_runs(&[hidden("p"), hidden("q")]);
        assert!(
            out.iter()
                .all(|p| p.carousel_index == -1 && p.run_ref.is_empty())
        );
    }
}
