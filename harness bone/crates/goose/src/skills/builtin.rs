use include_dir::{include_dir, Dir};

static BUILTIN_SKILLS_DIR: Dir = include_dir!("$CARGO_MANIFEST_DIR/src/skills/builtins");

pub fn get_all() -> Vec<&'static str> {
    let mut skills = Vec::new();
    collect_skills(&BUILTIN_SKILLS_DIR, true, &mut skills);
    skills
}

fn collect_skills(dir: &'static Dir<'static>, root: bool, skills: &mut Vec<&'static str>) {
    skills.extend(
        dir.files()
            .filter(|file| {
                (root && file.path().extension().is_some_and(|ext| ext == "md"))
                    || (!root
                        && file
                            .path()
                            .file_name()
                            .is_some_and(|name| name == "SKILL.md"))
            })
            .filter_map(|file| file.contents_utf8()),
    );

    for child in dir.dirs() {
        collect_skills(child, false, skills);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn includes_nested_workflow_skills() {
        let skills = get_all();

        assert!(
            skills
                .iter()
                .any(|skill| skill.contains("name: ngopilot-doc-guide")),
            "missing top-level built-in skill"
        );

        for name in [
            "careflow-paper-forms-to-excel",
            "careflow-meeting-notes",
            "careflow-government-forms",
            "roster-copilot",
        ] {
            assert!(
                skills
                    .iter()
                    .any(|skill| skill.contains(&format!("name: {name}"))),
                "missing built-in skill: {name}"
            );
        }
    }
}
