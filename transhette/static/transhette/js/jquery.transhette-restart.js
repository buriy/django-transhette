var checkWakeUp;
var noResponseFunc;
var polling;
var noresponse;

(function($) {
    $(document).ready(function(){
        $('.restartForm').submit(function() {
            var restart_url = $(this).find('span.ajax_restart').text();
            var wakeup_url = $(this).find('span.ajax_wakeup').text();
            var wait_div = $(this).find('div.wait');
            var submit_div = $(this).find('div.submit-row');
            var success_div = $(this).find('div.success');
            var error_div = $(this).find('div.error');
 
            checkWakeUp = function() {
                polling = setTimeout("checkWakeUp()", 5000);
                $.ajax({
                    url: wakeup_url,
                    dataType: 'json',
                    success: function(response) {
                        if (response && response.wakeup) { 
                            clearTimeout(polling);
                            clearTimeout(noresponse);
                            wait_div.hide();
                            success_div.show();
                        }; 
                    }
                });
            };
        
            noResponseFunc = function() {
                clearTimeout(polling);
                wait_div.hide();
                error_div.show();
            };

            submit_div.hide();
            wait_div.show();

            $.ajax({
                url: restart_url,
            });

            polling = setTimeout("checkWakeUp()", 5000);
            noresponse = setTimeout("noResponseFunc()", 20000);

            return false;
        });
    });
})(jQuery);
