import re
import sys

file_path = 'c:\\Users\\LENOVO\\purplemerit\\extractify\\frontend\\src\\components\\SharedLandingContent.tsx'

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace Name Input
content = re.sub(
    r'<input\s*type="text"\s*className="w-full h-12 rounded-\[8px\] bg-white border border-\[#d1d3d9\] px-3 text-\[#404040\] text-\[14px\] outline-none"\s*placeholder=""\s*aria-label=\{t\("reviewForm\.name"\)\}\s*data-node-id="27:692"\s*/>',
    '<input type="text" className="w-full h-12 rounded-[8px] bg-white border border-[#d1d3d9] px-3 text-[#404040] text-[14px] outline-none disabled:opacity-50" placeholder="" aria-label={t("reviewForm.name")} value={reviewName} onChange={(e) => setReviewName(e.target.value)} disabled={isSubmittingReview} data-node-id="27:692" />',
    content, count=1
)

# Replace Email Input
content = re.sub(
    r'<input\s*type="email"\s*className="w-full h-12 rounded-\[8px\] bg-white border border-\[#d1d3d9\] px-3 text-\[#404040\] text-\[14px\] outline-none"\s*placeholder=""\s*aria-label=\{t\("reviewForm\.email"\)\}\s*data-node-id="27:696"\s*/>',
    '<input type="email" className="w-full h-12 rounded-[8px] bg-white border border-[#d1d3d9] px-3 text-[#404040] text-[14px] outline-none disabled:opacity-50" placeholder="" aria-label={t("reviewForm.email")} value={reviewEmail} onChange={(e) => setReviewEmail(e.target.value)} disabled={isSubmittingReview} data-node-id="27:696" />',
    content, count=1
)

# Replace Textarea
content = re.sub(
    r'<textarea\s*className="w-full h-40 rounded-\[12px\] bg-white border border-\[#d1d3d9\] px-3 py-2 text-\[#404040\] text-\[14px\] leading-\[20px\] outline-none resize-none"\s*placeholder=\{t\("reviewForm\.placeholder"\)\}\s*aria-label=\{t\("reviewForm\.placeholder"\)\}\s*data-node-id="27:701"\s*/>',
    '<textarea className="w-full h-40 rounded-[12px] bg-white border border-[#d1d3d9] px-3 py-2 text-[#404040] text-[14px] leading-[20px] outline-none resize-none disabled:opacity-50" placeholder={t("reviewForm.placeholder")} aria-label={t("reviewForm.placeholder")} value={reviewText} onChange={(e) => setReviewText(e.target.value)} disabled={isSubmittingReview} data-node-id="27:701" />',
    content, count=1
)

# Replace Rating Stars
old_rating_pattern = r'\{Array\.from\(\{ length: 5 \}\)\.map\(\(_, i\) => \(\s*<button key=\{i\} type="button" className="size-\[26px\] shrink-0" aria-label=\{`Rate \$\{i \+ 1\} star`\}>\s*<svg viewBox="0 0 26 26" className="block size-full" fill="none" xmlns="http://www\.w3\.org/2000/svg">\s*<path\s*d="M13 3\.2L15\.9 9\.1L22\.4 10\.1L17\.7 14\.7L18\.8 21\.2L13 18\.1L7\.2 21\.2L8\.3 14\.7L3\.6 10\.1L10\.1 9\.1L13 3\.2Z"\s*fill="#9A9AA6"\s*stroke="#83838F"\s*strokeWidth="1"\s*strokeLinejoin="round"\s*/>\s*</svg>\s*</button>\s*\)\)\}'

new_rating_content = '''{Array.from({ length: 5 }).map((_, i) => {
                  const ratingValue = i + 1;
                  const isActive = ratingValue <= (hoverRating || reviewRating);
                  return (
                    <button
                      key={i}
                      type="button"
                      className="size-[26px] shrink-0 transition-transform hover:scale-110 focus:outline-none"
                      aria-label={`Rate ${ratingValue} star`}
                      onClick={() => setReviewRating(ratingValue)}
                      onMouseEnter={() => setHoverRating(ratingValue)}
                      onMouseLeave={() => setHoverRating(0)}
                      disabled={isSubmittingReview}
                    >
                      <svg viewBox="0 0 26 26" className="block size-full" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path
                          d="M13 3.2L15.9 9.1L22.4 10.1L17.7 14.7L18.8 21.2L13 18.1L7.2 21.2L8.3 14.7L3.6 10.1L10.1 9.1L13 3.2Z"
                          fill={isActive ? "#6f40dd" : "#9A9AA6"}
                          stroke={isActive ? "#6f40dd" : "#83838F"}
                          strokeWidth="1"
                          strokeLinejoin="round"
                          className="transition-colors duration-200"
                        />
                      </svg>
                    </button>
                  );
                })}'''

content = re.sub(old_rating_pattern, new_rating_content, content, count=1)


old_submit = r'<div className="bg-\[#6f40dd\] content-stretch flex items-center justify-center px-\[16px\] py-\[12px\] relative rounded-\[33px\] shrink-0 w-full" data-node-id="27:719">\s*<p className="font-\[\'Inter:Semi_Bold\',sans-serif\] font-semibold leading-\[normal\] not-italic relative shrink-0 text-\[16px\] text-white whitespace-nowrap" data-node-id="27:720">\s*\{t\("reviewForm\.submit"\)\}\s*</p>\s*</div>\s*</div>\s*</div>\s*<footer'

new_submit = '''{reviewMessage && (
              <div className={`w-full p-3 rounded-lg text-sm text-center ${reviewMessage.type === "success" ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"}`}>
                {reviewMessage.text}
              </div>
            )}

            <button
              type="button"
              onClick={handleReviewSubmit}
              disabled={isSubmittingReview}
              className="bg-[#6f40dd] hover:bg-[#5b32ba] transition-colors content-stretch flex items-center justify-center px-[16px] py-[12px] relative rounded-[33px] shrink-0 w-full disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
              data-node-id="27:719"
            >
              <p className="font-['Inter:Semi_Bold',sans-serif] font-semibold leading-[normal] not-italic relative shrink-0 text-[16px] text-white whitespace-nowrap" data-node-id="27:720">
                {isSubmittingReview ? "Submitting..." : t("reviewForm.submit")}
              </p>
            </button>
          </div>
        </div>
        <footer'''

content = re.sub(old_submit, new_submit, content, count=1)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Updates applied.")
