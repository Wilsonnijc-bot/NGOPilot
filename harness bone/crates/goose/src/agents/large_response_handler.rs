use crate::config::Config;
use rmcp::model::{CallToolResult, ContentBlock, ErrorData};
use serde_json::{json, Map, Value};
use std::io::Write;

const DEFAULT_LARGE_TEXT_THRESHOLD: usize = 200_000;
const STRUCTURED_FIELD_LIMIT: usize = 32 * 1024;
const STRUCTURED_PREVIEW_CHARS: usize = 2 * 1024;

fn large_text_threshold() -> usize {
    Config::global()
        .get_param::<usize>("GOOSE_MAX_TOOL_RESPONSE_SIZE")
        .unwrap_or(DEFAULT_LARGE_TEXT_THRESHOLD)
}

/// Process tool response and handle large text content
pub fn process_tool_response(
    response: Result<CallToolResult, ErrorData>,
) -> Result<CallToolResult, ErrorData> {
    let threshold = large_text_threshold();
    match response {
        Ok(mut result) => {
            let mut processed_contents = Vec::new();
            let mut spill_path = None;
            let mut compacted_large_response = false;

            for content in result.content {
                match content.as_text() {
                    Some(text_content) => {
                        // Check if text exceeds threshold
                        if text_content.text.chars().count() > threshold {
                            compacted_large_response = true;
                            // Write to temp file
                            match write_large_text_to_file(&text_content.text) {
                                Ok(file_path) => {
                                    spill_path.get_or_insert_with(|| file_path.clone());
                                    let message = compact_large_text_message(
                                        &text_content.text,
                                        threshold,
                                        &file_path,
                                    );
                                    processed_contents.push(ContentBlock::text(message));
                                }
                                Err(e) => {
                                    // If file writing fails, include original content with warning
                                    let warning = format!(
                                        "Warning: Failed to write large response to file: {}. Showing full content instead.\n\n{}",
                                        e,
                                        text_content.text
                                    );
                                    processed_contents.push(ContentBlock::text(warning));
                                }
                            }
                        } else {
                            // Keep original content for smaller texts
                            processed_contents.push(content);
                        }
                    }
                    None => {
                        // Pass through other content types unchanged
                        processed_contents.push(content);
                    }
                }
            }

            result.content = processed_contents;
            if let Some(structured_content) = result.structured_content.take() {
                let (structured_content, was_compacted) = compact_structured_content(
                    structured_content,
                    threshold,
                    spill_path.as_deref(),
                );
                compacted_large_response |= was_compacted;
                result.structured_content = Some(structured_content);
            }
            if compacted_large_response {
                trim_allocator();
            }
            Ok(result)
        }
        Err(e) => Err(e),
    }
}

fn compact_large_text_message(text: &str, threshold: usize, spill_path: &str) -> String {
    let character_count = text.chars().count();
    if let Ok(value) = serde_json::from_str::<Value>(text) {
        let (summary, _) = compact_structured_content(value, threshold, Some(spill_path));
        if let Ok(summary) = serde_json::to_string_pretty(&summary) {
            return format!(
                "The tool response was larger ({character_count} characters). The full response is stored at {spill_path}.\n\nCompact JSON summary:\n{summary}"
            );
        }
    }

    format!(
        "The response returned from the tool call was larger ({character_count} characters) and is stored in the file which you can use other tools to examine or search in: {spill_path}"
    )
}

fn compact_structured_content(
    value: Value,
    threshold: usize,
    existing_spill_path: Option<&str>,
) -> (Value, bool) {
    let Ok(encoded) = serde_json::to_string(&value) else {
        return (value, false);
    };
    let original_bytes = encoded.len();
    if original_bytes <= threshold {
        return (value, false);
    }

    let spill_path = existing_spill_path
        .map(ToOwned::to_owned)
        .or_else(|| write_large_text_to_file(&encoded).ok());
    let metadata = json!({
        "truncated": true,
        "original_bytes": original_bytes,
        "path": spill_path,
    });
    let mut compacted = Map::new();
    compacted.insert("_goose_large_response".to_string(), metadata.clone());

    if let Value::Object(fields) = value {
        for (key, field) in fields {
            if key == "_goose_large_response" {
                continue;
            }
            let Ok(field_json) = serde_json::to_string(&field) else {
                continue;
            };
            if field_json.len() <= STRUCTURED_FIELD_LIMIT {
                compacted.insert(key, field);
            } else {
                compacted.insert(
                    key,
                    json!({
                        "truncated": true,
                        "original_bytes": field_json.len(),
                        "preview": field_json
                            .chars()
                            .take(STRUCTURED_PREVIEW_CHARS)
                            .collect::<String>(),
                    }),
                );
            }
        }
    } else {
        compacted.insert(
            "value".to_string(),
            json!({
                "truncated": true,
                "original_bytes": original_bytes,
                "preview": encoded
                    .chars()
                    .take(STRUCTURED_PREVIEW_CHARS)
                    .collect::<String>(),
            }),
        );
    }

    let compacted = Value::Object(compacted);
    if serde_json::to_string(&compacted).is_ok_and(|json| json.len() <= threshold) {
        (compacted, true)
    } else {
        (
            json!({
                "_goose_large_response": metadata,
                "preview": encoded
                    .chars()
                    .take(STRUCTURED_PREVIEW_CHARS)
                    .collect::<String>(),
            }),
            true,
        )
    }
}

#[cfg(all(target_os = "linux", target_env = "gnu"))]
fn trim_allocator() {
    // SAFETY: malloc_trim only asks glibc to release currently free heap pages.
    unsafe {
        libc::malloc_trim(0);
    }
}

#[cfg(not(all(target_os = "linux", target_env = "gnu")))]
fn trim_allocator() {}

/// Write large text content to a temporary file
fn write_large_text_to_file(content: &str) -> Result<String, std::io::Error> {
    let mut file = tempfile::Builder::new()
        .prefix("goose_mcp_response_")
        .suffix(".txt")
        .tempfile()?;
    file.write_all(content.as_bytes())?;
    let (_, file_path) = file.keep()?;

    Ok(file_path.to_string_lossy().to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use rmcp::model::{ContentBlock, ErrorCode, ErrorData};
    use std::borrow::Cow;
    use std::fs;
    use std::path::Path;

    #[test]
    fn test_small_text_response_passes_through() {
        // Create a small text response
        let small_text = "This is a small text response";
        let content = ContentBlock::text(small_text.to_string());

        let response = Ok(CallToolResult::success(vec![content]));

        // Process the response
        let processed = process_tool_response(response).unwrap();

        // Verify the response is unchanged
        assert_eq!(processed.content.len(), 1);
        if let Some(text_content) = processed.content[0].as_text() {
            assert_eq!(text_content.text, small_text);
        } else {
            panic!("Expected text content");
        }
    }

    #[test]
    fn test_large_text_response_redirected_to_file() {
        // Create a text larger than the threshold
        let large_text = "a".repeat(DEFAULT_LARGE_TEXT_THRESHOLD + 1000);
        let content = ContentBlock::text(large_text.clone());

        let response = Ok(CallToolResult::success(vec![content]));

        // Process the response
        let processed = process_tool_response(response).unwrap();

        // Verify the response contains a message about the file
        assert_eq!(processed.content.len(), 1);
        if let Some(text_content) = processed.content[0].as_text() {
            assert!(text_content
                .text
                .contains("The response returned from the tool call was larger"));
            assert!(text_content.text.contains("characters"));

            // Extract the file path from the message
            let file_path = text_content
                .text
                .rsplit_once(": ")
                .expect("spill message should contain a file path")
                .1;
            let path = Path::new(file_path.trim());
            assert!(path.exists());
            assert_eq!(fs::read_to_string(path).unwrap(), large_text);
            fs::remove_file(path).unwrap();
        } else {
            panic!("Expected text content");
        }
    }

    #[test]
    fn test_large_json_text_preserves_actionable_summary() {
        let large_text = json!({
            "schema_version": "1.0",
            "tool": "roster_copilot",
            "job_id": "job_test",
            "state": "blocked",
            "result": {"rows": "x".repeat(DEFAULT_LARGE_TEXT_THRESHOLD)},
            "warnings": ["Missing source data"],
        })
        .to_string();
        let response = Ok(CallToolResult::success(vec![ContentBlock::text(
            large_text.clone(),
        )]));

        let processed = process_tool_response(response).unwrap();
        let text = &processed.content[0].as_text().unwrap().text;
        let summary_text = text
            .split_once("Compact JSON summary:\n")
            .expect("large JSON response should include a compact summary")
            .1;
        let summary: Value = serde_json::from_str(summary_text).unwrap();

        assert_eq!(summary["job_id"], "job_test");
        assert_eq!(summary["state"], "blocked");
        assert_eq!(summary["warnings"], json!(["Missing source data"]));
        assert_eq!(summary["result"]["truncated"], true);

        let path = summary["_goose_large_response"]["path"].as_str().unwrap();
        assert_eq!(fs::read_to_string(path).unwrap(), large_text);
        fs::remove_file(path).unwrap();
    }

    #[test]
    fn test_large_structured_response_is_compacted_and_preserves_metadata() {
        let large_text = "a".repeat(DEFAULT_LARGE_TEXT_THRESHOLD + 1000);
        let mut result = CallToolResult::success(vec![ContentBlock::text(large_text)]);
        result.structured_content = Some(json!({
            "schema_version": "1.0",
            "tool": "roster_copilot",
            "job_id": "job_test",
            "state": "blocked",
            "result": {"rows": "x".repeat(DEFAULT_LARGE_TEXT_THRESHOLD)},
            "warnings": ["Missing source data"],
        }));

        let processed = process_tool_response(Ok(result)).unwrap();
        let structured = processed.structured_content.unwrap();
        let marker = structured.get("_goose_large_response").unwrap();
        let result_marker = structured.get("result").unwrap();

        assert_eq!(structured["job_id"], "job_test");
        assert_eq!(structured["state"], "blocked");
        assert_eq!(structured["warnings"], json!(["Missing source data"]));
        assert_eq!(marker["truncated"], true);
        assert_eq!(result_marker["truncated"], true);
        assert!(serde_json::to_string(&structured).unwrap().len() < DEFAULT_LARGE_TEXT_THRESHOLD);

        let path = marker["path"].as_str().unwrap();
        assert!(Path::new(path).exists());
        fs::remove_file(path).unwrap();
    }

    #[test]
    fn test_image_content_passes_through() {
        // Create an image content
        let image_content = ContentBlock::image("base64data".to_string(), "image/png".to_string());

        let response = Ok(CallToolResult::success(vec![image_content]));

        // Process the response
        let processed = process_tool_response(response).unwrap();

        // Verify the response is unchanged
        assert_eq!(processed.content.len(), 1);
        if let Some(img) = processed.content[0].as_image() {
            assert_eq!(img.data, "base64data");
            assert_eq!(img.mime_type, "image/png");
        } else {
            panic!("Expected image content");
        }
    }

    #[test]
    fn test_mixed_content_handled_correctly() {
        // Create a response with mixed content types
        let small_text = ContentBlock::text("Small text");
        let large_text = ContentBlock::text("a".repeat(DEFAULT_LARGE_TEXT_THRESHOLD + 1000));
        let image = ContentBlock::image("image_data".to_string(), "image/jpeg".to_string());

        let response = Ok(CallToolResult::success(vec![small_text, large_text, image]));

        // Process the response
        let processed = process_tool_response(response).unwrap();

        // Verify each item is handled correctly
        assert_eq!(processed.content.len(), 3);

        // First item should be unchanged small text
        if let Some(text_content) = processed.content[0].as_text() {
            assert_eq!(text_content.text, "Small text");
        } else {
            panic!("Expected text content");
        }

        // Second item should be a message about the file
        if let Some(text_content) = processed.content[1].as_text() {
            assert!(text_content
                .text
                .contains("The response returned from the tool call was larger"));

            // Extract the file path and clean up
            let file_path = text_content
                .text
                .rsplit_once(": ")
                .expect("spill message should contain a file path")
                .1;
            fs::remove_file(Path::new(file_path.trim())).unwrap();
        } else {
            panic!("Expected text content");
        }

        // Third item should be unchanged image
        if let Some(img) = processed.content[2].as_image() {
            assert_eq!(img.data, "image_data");
            assert_eq!(img.mime_type, "image/jpeg");
        } else {
            panic!("Expected image content");
        }
    }

    #[test]
    fn test_error_response_passes_through() {
        // Create an error response
        let error = ErrorData {
            code: ErrorCode::INTERNAL_ERROR,
            message: Cow::from("Test error"),
            data: None,
        };
        let response: Result<CallToolResult, ErrorData> = Err(error);

        // Process the response
        let processed = process_tool_response(response);

        // Verify the error is passed through unchanged
        assert!(processed.is_err());
        match processed {
            Err(err) => {
                assert_eq!(err.code, ErrorCode::INTERNAL_ERROR);
                assert_eq!(err.message, "Test error");
            }
            _ => panic!("Expected execution error"),
        }
    }

    #[test]
    fn test_large_response_files_have_unique_paths() {
        let first_path = write_large_text_to_file("first response").unwrap();
        let second_path = write_large_text_to_file("second response").unwrap();
        let paths_are_distinct = first_path != second_path;
        let first_content = fs::read_to_string(&first_path).unwrap();
        let second_content = fs::read_to_string(&second_path).unwrap();

        fs::remove_file(&first_path).unwrap();
        if paths_are_distinct {
            fs::remove_file(&second_path).unwrap();
        }

        assert!(paths_are_distinct);
        assert_eq!(first_content, "first response");
        assert_eq!(second_content, "second response");
    }

    #[cfg(unix)]
    #[test]
    fn test_large_response_file_is_owner_only() {
        use std::os::unix::fs::PermissionsExt;

        let file_path = write_large_text_to_file("sensitive response").unwrap();
        let metadata = fs::metadata(&file_path).unwrap();
        let mode = metadata.permissions().mode();
        let content = fs::read_to_string(&file_path).unwrap();
        fs::remove_file(&file_path).unwrap();

        assert_eq!(mode & 0o077, 0);
        assert_eq!(content, "sensitive response");
    }
}
